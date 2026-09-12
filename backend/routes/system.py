# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""
Velluma - AI Novel Writing Assistant
Copyright (C) 2026 Velluma Project Contributors

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

"""
系统健康检查与配置路由模块。

职责：提供系统级 API，用于健康检查和运行时配置查询。

业务场景：
- 健康检查（/health）
- 获取后端实际端口（开发环境动态分配）
- 系统信息查询
- 模型连接测试（含推理模式支持检测）

设计说明：
- /health 用于容器编排系统（K8s/Docker）健康探测
- 端口获取解决开发环境动态切换端口的问题

数据来源：
- 端口信息来自 core/config.py 的运行时配置
"""

import logging

from fastapi import APIRouter, HTTPException

from backend.core.config import get_actual_port, check_reasoning_support
from backend.core.model_config import (
    resolve_model_name,
    get_default_reasoning_config,
    get_model_profile,
    get_model_config,
    get_embedding_connection,
    update_llm_profile,
    update_embedding_config,
    get_model_prices,
    update_model_prices,
    get_deai_config,
    update_deai_config,
    get_model_presets,
    get_model_preset,
    upsert_model_preset,
    delete_model_preset,
    apply_model_preset,
    maybe_capture_outgoing_slot,
)
from backend.services.llm import get_proxy_config, set_proxy_config, call_llm
from backend.services.llm.embedding import probe_embedding
from backend.services.llm.vendor_profiles import vendor_catalog
from backend.services.utils.logging import ServiceLogger, LOG_PREFIX_SYSTEM
from backend.schemas import (
    ProxyConfig, ModelTestRequest, ModelTestResponse, ModelConfigUpdate,
    ModelPricesUpdate,
    ModelPresetSave, ModelPresetApply,
    DeaiTestRequest, DeaiTestResponse,
)

router = APIRouter(prefix="/api", tags=["system"])
logger = logging.getLogger(__name__)
svc_logger = ServiceLogger(logger, LOG_PREFIX_SYSTEM)


# =============================================================================
# 健康检查与配置查询
 # =============================================================================

@router.get("/health")
async def health_check():
    """业务目的：提供基础健康检查端点，用于服务监控和负载均衡探测。

    用途：
    - Kubernetes/容器编排探针
    - 负载均衡健康检测
    - 运维监控确认服务存活

    副作用：
    - 无数据库操作，轻量级接口

    设计考量：
    - 返回固定值而非实时系统指标（CPU/内存等）
    - 简化监控复杂度，避免频繁采样
    - 若需要详细监控，应使用专门指标端点（如 /metrics）
    """
    return {"status": "ok", "service": "StoryWeaver-Core"}


@router.get("/port")
async def get_port():
    """业务目的：返回服务实际监听端口，用于容器环境下的服务发现。

    背景：
    - 容器化部署时，PORT 可能通过环境变量动态指定
    - 前端或网关需要知道实际端口进行连接

    数据来源：
    - get_actual_port() 读取环境变量或配置文件
    - 默认为 8000，开发环境常用

    权衡点：
    - 为什么不直接硬编码？
      因为容器环境端口映射的灵活性要求
    - 为什么不返回 IP？
      因为单实例部署场景，客户端通过网关访问
    """
    return {"port": get_actual_port()}


@router.get("/system/proxy")
async def get_proxy_config_endpoint():
    """获取当前代理配置"""
    return get_proxy_config()


@router.put("/system/proxy")
async def update_proxy_config_endpoint(config: ProxyConfig):
    """更新代理配置"""
    set_proxy_config(config.enabled, config.url)
    return get_proxy_config()


# =============================================================================
# 模型配置（设置面板）
# =============================================================================

def _mask_api_key(key: str) -> str:
    """API Key 掩码：仅保留首尾各 4 位，避免明文经 HTTP 传输。"""
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    return f"{key[:4]}****{key[-4:]}"


def _serialize_profile(role: str) -> dict:
    profile = get_model_profile(role)
    return {
        "api_key_masked": _mask_api_key(profile["api_key"]),
        "has_api_key": bool(profile["api_key"]),
        "base_url": profile["base_url"],
        "model": profile["model"],
        "enabled": profile["enabled"],
        "effort": profile["effort"],
    }


def _serialize_wash_profile() -> dict:
    """洗涤槽序列化：返回原始配置（不做 creative 回退），未配置时字段为空。

    与 _serialize_profile 的区别：get_model_profile("wash") 会在未配置时
    回退到 creative，直接复用会让前端把 creative 的值显示成 wash 的配置，
    保存时还会把这些值固化进 wash 槽。configured 标志供前端提示"跟随创意模型"。
    """
    raw = get_model_config().get("llm", {}).get("wash", {})
    return {
        "api_key_masked": _mask_api_key(raw.get("api_key", "")),
        "has_api_key": bool(raw.get("api_key")),
        "base_url": raw.get("base_url", ""),
        "model": raw.get("model", ""),
        "enabled": raw.get("enabled", False),
        "effort": raw.get("effort", "low"),
        "configured": bool(raw.get("model") and raw.get("api_key")),
    }


def _serialize_embedding() -> dict:
    """Embedding 配置序列化：自管字段原样回（Key 掩码）+ 跟随模式的实际连接预览。

    follow_llm=true 时连接取自文本模型槽（creative 优先、缺 Key 回退 reasoning），
    inherited 把这份「实际生效的连接」带回前端展示，避免用户以为跟随生效了
    而文本模型槽其实没配 Key。
    """
    embedding = get_model_config().get("embedding", {})
    connection = get_embedding_connection()
    following = connection["follow_llm"]
    return {
        "api_key_masked": _mask_api_key(embedding.get("api_key", "")),
        "has_api_key": bool(embedding.get("api_key")),
        "base_url": embedding.get("base_url", ""),
        "model": embedding.get("model", "text-embedding-v2"),
        "dimensions": embedding.get("dimensions", 1536),
        "follow_llm": following,
        "inherited": {
            "source": connection["source"] if following else None,
            "base_url": connection["base_url"] if following else "",
            "has_api_key": bool(connection["api_key"]) if following else False,
        },
    }


def _serialize_deai() -> dict:
    """deai 去AI味小模型配置序列化（deai/ 子项目，docs/deai-integration.md）。

    get_deai_config 已做默认值兜底（model/base_url 常有默认），序列化时
    raw 取原始存储值供表单回显，effective 取兜底后值供提示。
    """
    raw = get_model_config().get("deai", {})
    effective = get_deai_config()
    return {
        "api_key_masked": _mask_api_key(raw.get("api_key", "")),
        "has_api_key": bool(raw.get("api_key")),
        "base_url": raw.get("base_url", ""),
        "effective_base_url": effective["base_url"],
        "model": raw.get("model", ""),
        "effective_model": effective["model"],
        "enabled": bool(raw.get("enabled", False)),
        "configured": bool(raw.get("enabled") and raw.get("api_key") and (raw.get("model") or effective["model"])),
    }


def _serialize_model_config() -> dict:
    """序列化完整模型配置（API Key 掩码后返回）"""
    return {
        "llm": {
            "reasoning": _serialize_profile("reasoning"),
            "creative": _serialize_profile("creative"),
            "wash": _serialize_wash_profile(),
        },
        "embedding": _serialize_embedding(),
        "deai": _serialize_deai(),
        "proxy": get_proxy_config(),
    }


@router.get("/system/model-config")
async def get_model_config_endpoint():
    """获取模型配置（LLM / Embedding / 代理），API Key 以掩码返回"""
    return _serialize_model_config()


@router.get("/system/model-catalog")
async def get_model_catalog_endpoint():
    """厂商能力目录（2026-08-28 五厂商调研，docs/model-vendor-matrix.md）。

    前端设置弹窗消费：选厂商 → 自动填 base_url + 模型候选 + 能力提示
    （采样锁定/强制思考/定价速览）。模型名永远允许自由输入，目录只是候选。
    """
    return {"vendors": vendor_catalog()}


@router.put("/system/model-config")
async def update_model_config_endpoint(update: ModelConfigUpdate):
    """更新模型配置并持久化到 model_config.json。

    副作用：
    - 未提供的字段保持原值；api_key 传空字符串/None 表示不修改
    - LLM 与代理配置保存后立即生效（每次调用实时读取）
    - embedding.dimensions 变更需重启后端，启动迁移会删列重建向量数据（破坏性）
    """
    for role, profile in (
        ("reasoning", update.reasoning),
        ("creative", update.creative),
        ("wash", update.wash),
    ):
        if profile is None:
            continue
        fields = profile.model_dump(exclude_none=True)
        # 空 Key 或掩码回显值（GET 只回掩码，前端原样回传）都视为保持不变——
        # 掩码是 truthy，旧条件拦不住，会把 "sk-1a****xyz" 当真 Key 覆盖落盘
        if not fields.get("api_key") or "****" in str(fields.get("api_key")):
            fields.pop("api_key", None)
        if fields:
            # 安全网：连接三件套即将被覆盖时先把旧值自动存为预设（内部自判
            # 未变/不完整/已存档，静默跳过），「切走丢 Key」从根上堵死
            maybe_capture_outgoing_slot(role, fields)
            update_llm_profile(role, fields)

    if update.embedding is not None:
        fields = update.embedding.model_dump(exclude_none=True)
        # 掩码回显防御同上（embedding Key 同样只以掩码形态回显）
        if not fields.get("api_key") or "****" in str(fields.get("api_key")):
            fields.pop("api_key", None)
        if fields:
            update_embedding_config(fields)

    if update.deai is not None:
        fields = update.deai.model_dump(exclude_none=True)
        # 掩码回显防御同上（deai Key 同样只以掩码形态回显）
        if not fields.get("api_key") or "****" in str(fields.get("api_key")):
            fields.pop("api_key", None)
        if fields:
            update_deai_config(fields)

    if update.proxy is not None:
        set_proxy_config(update.proxy.enabled, update.proxy.url)

    svc_logger.info("模型配置已更新")
    return _serialize_model_config()


def _serialize_preset(preset: dict) -> dict:
    """预设出参：Key 只回掩码（明文仅存 json，切换由服务端 apply 完成）。"""
    return {
        "id": preset["id"],
        "name": preset["name"],
        "source": preset.get("source", "manual"),
        "model": preset.get("model", ""),
        "base_url": preset.get("base_url", ""),
        "enabled": preset.get("enabled", False),
        "effort": preset.get("effort", "medium"),
        "has_api_key": bool(preset.get("api_key")),
        "api_key_masked": _mask_api_key(preset.get("api_key", "")),
    }


def _serialize_presets() -> list:
    return [_serialize_preset(p) for p in get_model_presets()]


# =============================================================================
# 模型配置预设（2026-09-11 快速切换）：换厂商/换 Key 前整套存档，下拉一点切回
# =============================================================================

@router.get("/system/model-presets")
async def get_model_presets_endpoint():
    """读预设池（Key 掩码）。设置弹窗两槽共用的快速切换下拉。"""
    return {"presets": _serialize_presets()}


@router.post("/system/model-presets")
async def save_model_preset_endpoint(payload: ModelPresetSave):
    """保存/覆盖预设（同名覆盖），返回最新预设池。

    copy_from_role 语义：以该槽位已保存配置为底（含槽内明文 Key——表单
    Key 框留空=「保持不变」，也要能把整套连接连 Key 存档），显式字段
    覆盖底值。前端「存为预设」恒带 copy_from_role，保证未保存的表单
    改动（Key 除外）与已存 Key 都进预设。
    """
    base: dict = {}
    if payload.copy_from_role in ("reasoning", "creative"):
        base = get_model_config().get("llm", {}).get(payload.copy_from_role, {}) or {}
    fields = {
        "model": (payload.model or "").strip() or base.get("model", ""),
        "base_url": (payload.base_url or "").strip() or base.get("base_url", ""),
        "api_key": (payload.api_key or "").strip() or base.get("api_key", ""),
        # 显式掩码回显值防御（同 PUT /system/model-config）
        "enabled": payload.enabled if payload.enabled is not None else bool(base.get("enabled", False)),
        "effort": (payload.effort or "").strip() or base.get("effort", "medium"),
    }
    if "****" in str(payload.api_key or ""):
        fields["api_key"] = base.get("api_key", "")
    # schema 的 min_length 拦不住纯空白名（"   "），这里显式 422 而非落 ValueError 500
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="预设名不能为空")
    existing_names = {p["name"] for p in get_model_presets()}
    upsert_model_preset(name, fields, source="manual")
    return {
        "presets": _serialize_presets(),
        "overwrote": name in existing_names,
    }


@router.delete("/system/model-presets/{preset_id}")
async def delete_model_preset_endpoint(preset_id: str):
    """删预设（幂等：删不存在的 id 也返回成功与最新列表）。"""
    delete_model_preset(preset_id)
    return {"presets": _serialize_presets()}


@router.post("/system/model-presets/{preset_id}/apply")
async def apply_model_preset_endpoint(preset_id: str, payload: ModelPresetApply):
    """预设切回：五件整卡写入指定槽位并立即生效（每次调用实时读取配置）。

    旧值先行自动存档（同签名已存档则静默跳过），切换动作本身无损。
    返回最新模型配置供表单就地刷新——只动一个槽，另一槽的未保存表单
    改动不受牵连（前端按槽应用，不做全量 applyConfig）。
    """
    preset = get_model_preset(preset_id)
    if preset is None:
        raise HTTPException(status_code=404, detail=f"预设不存在: {preset_id}")
    if payload.role not in ("reasoning", "creative"):
        raise HTTPException(status_code=422, detail=f"role 只能是 reasoning/creative: {payload.role}")
    captured = maybe_capture_outgoing_slot(payload.role, preset)
    apply_model_preset(preset_id, payload.role)
    return {
        "presets": _serialize_presets(),
        "config": _serialize_model_config(),
        "applied": {"id": preset["id"], "name": preset["name"]},
        "auto_captured": captured["name"] if captured else None,
    }


# =============================================================================
# 模型价目表（成本核算，2026-09-11）——数据页 AI 消耗卡按价算钱的数据面
# =============================================================================

@router.get("/system/model-prices")
async def get_model_prices_endpoint():
    """读价目表（元/百万 token，按模型名键控；无 prices 节 = 空表全未计价）。"""
    return {"prices": get_model_prices()}


@router.put("/system/model-prices")
async def update_model_prices_endpoint(update: ModelPricesUpdate):
    """整表覆写价目并持久化到 model_config.json。

    价格按各厂商公布页自填（厂商无统一计价 API）；保存后立即生效——
    usage 端点每次请求实时读表。空 prices = 清空回到未计价态。
    """
    saved = update_model_prices(
        {model: entry.model_dump(exclude_none=True) for model, entry in update.prices.items()}
    )
    svc_logger.info(f"模型价目表已更新（{len(saved)} 个模型）")
    return {"prices": saved}


# =============================================================================
# deai 小模型试一试（deai/ 子项目，docs/deai-integration.md）
# =============================================================================

# 内置示例：带典型 AI 味（套话连接+空泛总结），落在 ≤100 字契约窗内
DEAI_TEST_SAMPLE = "综上所述，这轮改动显著提升了整体体验，为后续的迭代夯实了基础。"


@router.post("/system/deai/test", response_model=DeaiTestResponse)
async def test_deai_model(request: DeaiTestRequest):
    """deai 去AI味小模型实测（设置面板「试一试」按钮）。

    表单实时值探测（未保存也能测，同 embedding probe 契约）：model /
    api_key / base_url 留空沿用已保存配置。走 polish_fragment 全链路，
    含契约§6 事实闸保底——事实闸回退**不算失败**（模型答了、闸门拦了，
    恰是保底机制在工作的证据）；网络/HTTP 异常与未配置才算失败。
    """
    import time

    from backend.services.deai import polish_fragment

    text = (request.text or DEAI_TEST_SAMPLE).strip()
    model = (request.model or "").strip() or get_deai_config()["model"]
    start = time.perf_counter()
    try:
        result = await polish_fragment(
            text,
            model=request.model or None,
            api_key=request.api_key or None,
            base_url=request.base_url or None,
        )
    except Exception as e:
        return DeaiTestResponse(
            success=False, message=f"调用异常: {e}",
            input_text=text, output_text=text, model=model,
            elapsed_ms=round((time.perf_counter() - start) * 1000, 1),
        )
    elapsed_ms = round((time.perf_counter() - start) * 1000, 1)

    if result.skipped:
        success, message = False, f"未发起调用：{result.reason}"
    elif result.applied:
        success = True
        message = "改写被采纳" + (f"（带警告：{'；'.join(result.warnings)}）" if result.warnings else "")
    elif result.reason.startswith("事实被改"):
        success = True
        message = f"模型动了事实，契约保底已回退原文（闸门生效）——{result.reason}"
    else:
        success, message = False, f"调用失败：{result.reason}"

    return DeaiTestResponse(
        success=success,
        message=message,
        input_text=text,
        output_text=result.text,
        applied=result.applied,
        skipped=result.skipped,
        fallback_reason=result.reason,
        warnings=result.warnings,
        model=model,
        elapsed_ms=elapsed_ms,
    )


# =============================================================================
# 模型连接测试
# =============================================================================

@router.post("/system/test-model", response_model=ModelTestResponse)
async def test_model_connection(request: ModelTestRequest):
    """
    测试模型连接并检测推理模式支持。
    
    业务目的：
    - 验证 API Key 和 Base URL 是否正确配置
    - 检测 reasoning 和 creative 两个文本模型是否可用；
      embedding 已配置（或表单填了值）时一并探测向量模型连接与维度匹配
      （wash 洗涤槽 UI 已隐藏，不参与连接测试）
    - 如果启用推理模式，检测模型是否支持推理功能

    测试流程：
    1. 分别测试 reasoning 和 creative 模型
    2. 探测向量模型（用表单实时值，未保存也能测；未配置则跳过不算失败）
    3. 检查模型名称是否在已知支持推理的列表中
    4. 如果启用推理，尝试带推理参数的请求
    
    Returns:
        ModelTestResponse: 包含连接状态、推理支持信息等
    """
    import time
    
    start_time = time.perf_counter()
    reasoning_model = resolve_model_name(model_type="reasoning")
    creative_model = resolve_model_name(model_type="creative")
    
    reasoning_profile = get_model_profile("reasoning")
    creative_profile = get_model_profile("creative")
    
    # 构建推理配置（如果启用）
    reasoning_config = None
    reasoning_enabled = request.reasoning_enabled
    reasoning_effort = request.reasoning_effort

    if reasoning_enabled is None:
        default_cfg = get_default_reasoning_config("reasoning")
        # 2026-08-25 语义修复后：enabled=False 也返回非空（显式关闭）——
        # 此处要的是「思考是否开启」，必须看标志位而非真值
        if default_cfg and default_cfg.get("reasoning", {}).get("enabled"):
            reasoning_config = default_cfg
            reasoning_enabled = True
            reasoning_effort = default_cfg.get("reasoning", {}).get("effort", "medium")
        else:
            reasoning_config = default_cfg  # 显式关闭也透传（让测试连接走真实语义）
            reasoning_enabled = False
    elif reasoning_enabled:
        reasoning_config = {
            "reasoning": {
                "enabled": True,
                "effort": reasoning_effort or "medium"
            }
        }

    test_prompt = "请回复'连接测试成功'这六个字，不要输出其他内容。"
    
    # 测试 reasoning 模型
    reasoning_success = False
    reasoning_response = ""
    reasoning_error = ""
    try:
        reasoning_response = await call_llm(
            system_prompt="你是一个测试助手。请严格按照用户的要求回复。",
            user_prompt=test_prompt,
            model=reasoning_model,
            model_type="reasoning",
            temperature=0.1,
            max_tokens=50,
            reasoning_config=reasoning_config,
        )
        reasoning_success = True
    except Exception as e:
        reasoning_error = str(e)
    
    # 测试 creative 模型
    creative_success = False
    creative_response = ""
    creative_error = ""
    try:
        creative_response = await call_llm(
            system_prompt="你是一个测试助手。请严格按照用户的要求回复。",
            user_prompt=test_prompt,
            model=creative_model,
            model_type="creative",
            temperature=0.7,
            max_tokens=50,
        )
        creative_success = True
    except Exception as e:
        creative_error = str(e)

    # 向量模型探测（表单实时值，未保存也能测；wash 槽 UI 已隐藏，不参与测试）
    emb_overrides = request.embedding.model_dump(exclude_none=True) if request.embedding else None
    emb_probe = await probe_embedding(emb_overrides)

    elapsed_ms = (time.perf_counter() - start_time) * 1000

    # 检查推理模式支持
    reasoning_supported, reasoning_message = check_reasoning_support(reasoning_model)
    creative_supported, creative_message = check_reasoning_support(creative_model)

    # 构建返回消息
    messages = []
    if reasoning_success:
        messages.append(f"推理模型 ({reasoning_model}): 连接成功")
    else:
        messages.append(f"推理模型 ({reasoning_model}): 连接失败 - {reasoning_error[:100]}")

    if creative_success:
        messages.append(f"创意模型 ({creative_model}): 连接成功")
    else:
        messages.append(f"创意模型 ({creative_model}): 连接失败 - {creative_error[:100]}")

    if not emb_probe["configured"]:
        messages.append("向量模型: 未配置（跳过，记忆走结构化+词法默认流）")
    else:
        messages.append(f"向量模型 ({emb_probe['model']}): {emb_probe['message']}")

    # 向量模型「已配置但不可用」= 静默退化风险（运行时只会记日志然后回退词法流），
    # 必须在测试结果里显式反映为失败；未配置跳过则不影响整体结论
    overall_success = (reasoning_success or creative_success) and (
        not emb_probe["configured"] or emb_probe["success"]
    )

    return ModelTestResponse(
        success=overall_success,
        message="; ".join(messages),
        model_info={
            "reasoning_model": reasoning_model,
            "creative_model": creative_model,
            "reasoning_base_url": reasoning_profile["base_url"],
            "creative_base_url": creative_profile["base_url"],
            "reasoning_success": reasoning_success,
            "creative_success": creative_success,
            "embedding_configured": emb_probe["configured"],
            "embedding_model": emb_probe["model"],
            "embedding_success": emb_probe["success"],
            "embedding_source": emb_probe["source"],
            "embedding_dimensions_returned": emb_probe["dimensions_returned"],
            "embedding_dimensions_expected": emb_probe["dimensions_expected"],
        },
        reasoning_supported=reasoning_supported,
        reasoning_message=reasoning_message,
        response_time_ms=round(elapsed_ms, 2)
    )
