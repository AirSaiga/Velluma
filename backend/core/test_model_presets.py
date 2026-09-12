# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""模型配置预设（presets 节）单测——CONFIG_PATH 打桩到临时文件（同 test_pricing 契约）。

覆盖：CRUD 往返 / 同名覆盖保 id / 签名去重（自动存档不堆积）/
自动存档触发与跳过条件（连接未变·旧值不完整·已有同签名）/
apply 整卡写入槽位含明文 Key / 命名撞车 (2) 后缀。
"""
import json

import pytest

import backend.core.model_config as mc


@pytest.fixture()
def stubbed_config(tmp_path, monkeypatch):
    """临时 model_config.json：creative 槽完整、reasoning 槽半态（无 Key）。"""
    cfg_path = tmp_path / "model_config.json"
    cfg_path.write_text(json.dumps({
        "llm": {
            "creative": {
                "model": "kimi-k2.6",
                "api_key": "sk-creative-key",
                "base_url": "https://api.moonshot.cn/v1",
                "enabled": True,
                "effort": "medium",
            },
            "reasoning": {
                "model": "deepseek-flash",
                "api_key": "",
                "base_url": "https://api.deepseek.com/v1",
                "enabled": False,
                "effort": "medium",
            },
        },
    }), encoding="utf-8")
    monkeypatch.setattr(mc, "CONFIG_PATH", str(cfg_path))
    monkeypatch.setattr(mc, "_config_cache", None)
    return cfg_path


class TestPresetCrud:

    def test_upsert_get_delete_roundtrip(self, stubbed_config):
        saved = mc.upsert_model_preset("DeepSeek 主力", {
            "model": "deepseek-flash",
            "api_key": "sk-ds",
            "base_url": "https://api.deepseek.com/v1",
            "enabled": True,
            "effort": "high",
        })
        assert saved["id"] and saved["source"] == "manual"

        presets = mc.get_model_presets()
        assert len(presets) == 1
        assert presets[0]["name"] == "DeepSeek 主力"
        assert presets[0]["api_key"] == "sk-ds"

        assert mc.get_model_preset(saved["id"])["name"] == "DeepSeek 主力"
        assert mc.get_model_preset("no-such-id") is None

        assert mc.delete_model_preset(saved["id"]) is True
        assert mc.get_model_presets() == []
        # 幂等删除
        assert mc.delete_model_preset(saved["id"]) is False

    def test_same_name_overwrite_keeps_id(self, stubbed_config):
        first = mc.upsert_model_preset("主力", {"model": "m1", "api_key": "k1"})
        second = mc.upsert_model_preset("主力", {"model": "m2", "api_key": "k2", "source": "nonsense"})
        assert second["id"] == first["id"]
        presets = mc.get_model_presets()
        assert len(presets) == 1
        assert presets[0]["model"] == "m2"
        # 未知 source 值归一为 manual
        assert presets[0]["source"] == "manual"

    def test_empty_name_rejected(self, stubbed_config):
        with pytest.raises(ValueError):
            mc.upsert_model_preset("   ", {"model": "m"})

    def test_malformed_entries_dropped(self, tmp_path, monkeypatch):
        cfg_path = tmp_path / "model_config.json"
        cfg_path.write_text(json.dumps({
            "llm": {},
            "presets": [
                {"id": "a", "name": "ok", "model": "m"},
                {"name": "no-id"},           # 缺 id → 丢弃
                {"id": "b"},                  # 缺 name → 丢弃
                "not-a-dict",                 # 形状错 → 丢弃
                {"id": "c", "name": "bad-effort", "effort": "ultra"},  # effort 归一 medium
            ],
        }), encoding="utf-8")
        monkeypatch.setattr(mc, "CONFIG_PATH", str(cfg_path))
        monkeypatch.setattr(mc, "_config_cache", None)

        presets = mc.get_model_presets()
        assert [p["name"] for p in presets] == ["ok", "bad-effort"]
        assert presets[1]["effort"] == "medium"


class TestAutoCapture:
    """maybe_capture_outgoing_slot：安全网的触发与全部跳过条件。"""

    def test_capture_on_connection_change(self, stubbed_config):
        captured = mc.maybe_capture_outgoing_slot("creative", {"model": "glm-5.2"})
        assert captured is not None
        assert captured["source"] == "auto"
        assert captured["model"] == "kimi-k2.6"
        assert captured["api_key"] == "sk-creative-key"
        # 槽位本身未被该函数改动（写入是调用方 update_llm_profile 的事）
        assert mc.get_llm_config()["creative"]["model"] == "kimi-k2.6"

    def test_no_capture_when_connection_unchanged(self, stubbed_config):
        # 只改思考开关/力度：连接三件套未变 → 不存档
        assert mc.maybe_capture_outgoing_slot("creative", {"enabled": True, "effort": "high"}) is None
        # 空字段（noop 保存）同理
        assert mc.maybe_capture_outgoing_slot("creative", {}) is None

    def test_no_capture_when_slot_incomplete(self, stubbed_config):
        # reasoning 槽无 Key（跟随 creative 的半态）→ 无 Key 可丢，不存
        assert mc.maybe_capture_outgoing_slot("reasoning", {"model": "glm-5.2"}) is None
        # wash 槽不在收录范围
        assert mc.maybe_capture_outgoing_slot("wash", {"model": "x"}) is None

    def test_no_capture_when_signature_already_archived(self, stubbed_config):
        mc.upsert_model_preset("手动存的", {
            "model": "kimi-k2.6",
            "api_key": "sk-creative-key",
            "base_url": "https://api.moonshot.cn/v1",
        })
        # 已有同签名预设（无论 manual/auto）→ 自动存档不再堆第二条
        assert mc.maybe_capture_outgoing_slot("creative", {"model": "glm-5.2"}) is None
        assert len(mc.get_model_presets()) == 1

    def test_new_key_triggers_capture(self, stubbed_config):
        # 换 Key 也是连接变更：旧 Key 必须被存档
        captured = mc.maybe_capture_outgoing_slot("creative", {"api_key": "sk-new-key"})
        assert captured is not None
        assert captured["api_key"] == "sk-creative-key"

    def test_capture_then_apply_roundtrip_restores_key(self, stubbed_config):
        """端到端语义：切走 → 自动存档 → 切回，Key 原样恢复且不堆积存档。"""
        captured = mc.maybe_capture_outgoing_slot("creative", {"model": "glm-5.2", "api_key": "sk-glm"})
        assert captured is not None
        mc.update_llm_profile("creative", {"model": "glm-5.2", "api_key": "sk-glm"})

        # 切回前：当前 glm 连接尚无存档 → 再存一条（旧值不丢）
        glm_archive = mc.maybe_capture_outgoing_slot("creative", captured)
        assert glm_archive is not None
        assert glm_archive["model"] == "glm-5.2"
        assert glm_archive["api_key"] == "sk-glm"
        # 同签名已存档 → 第二次不再堆
        assert mc.maybe_capture_outgoing_slot("creative", captured) is None
        assert len([p for p in mc.get_model_presets() if p["model"] == "glm-5.2"]) == 1

        mc.apply_model_preset(captured["id"], "creative")
        profile = mc.get_llm_config()["creative"]
        assert profile["model"] == "kimi-k2.6"
        assert profile["api_key"] == "sk-creative-key"
        assert profile["base_url"] == "https://api.moonshot.cn/v1"

    def test_auto_name_collision_gets_suffix(self, stubbed_config):
        # 同模型同厂商、不同 Key：签名不同（都会存）但显示名相同 → 后一条加 (2)
        first = mc.maybe_capture_outgoing_slot("creative", {"model": "glm-5.2"})
        assert first is not None
        mc.update_llm_profile("creative", {"api_key": "sk-another-key"})
        second = mc.maybe_capture_outgoing_slot("creative", {"model": "glm-5.2"})
        assert second is not None
        assert second["api_key"] == "sk-another-key"
        assert second["name"] == f"{first['name']} (2)"


class TestApplyPreset:

    def test_apply_writes_all_five_fields(self, stubbed_config):
        saved = mc.upsert_model_preset("GLM", {
            "model": "glm-5.2",
            "api_key": "sk-glm",
            "base_url": "https://open.bigmodel.cn/api/paas/v4",
            "enabled": False,
            "effort": "low",
        })
        mc.apply_model_preset(saved["id"], "reasoning")
        profile = mc.get_llm_config()["reasoning"]
        assert profile == {
            "model": "glm-5.2",
            "api_key": "sk-glm",
            "base_url": "https://open.bigmodel.cn/api/paas/v4",
            "enabled": False,
            "effort": "low",
        }

    def test_apply_rejects_unknown_preset_and_role(self, stubbed_config):
        saved = mc.upsert_model_preset("x", {"model": "m"})
        with pytest.raises(KeyError):
            mc.apply_model_preset("no-such-id", "creative")
        with pytest.raises(ValueError):
            mc.apply_model_preset(saved["id"], "wash")


def test_auto_preset_display_name_uses_vendor_label(stubbed_config):
    name = mc._auto_preset_display_name({
        "model": "kimi-k2.6",
        "base_url": "https://api.moonshot.cn/v1",
    })
    assert "kimi-k2.6" in name
    # 识别到厂商时带标签（具体文案随目录演进，只锚定包含模型名）
    # 未知域名退化为纯模型名
    assert mc._auto_preset_display_name({"model": "my-model", "base_url": "https://llm.internal/v1"}) == "my-model"


class TestPresetRoutes:
    """路由层冒烟（system 路由无 DB 依赖，最小 FastAPI 应用挂载）：
    掩码出参 / copy_from_role 取槽内明文 Key / apply 切回 / 纯空白名 422 / 删除幂等。"""

    def test_route_flow(self, stubbed_config):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from backend.routes.system import router

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        # 保存预设：copy_from_role=creative 且表单 Key 留空 → 槽内明文 Key 入档
        resp = client.post("/api/system/model-presets", json={
            "name": "Kimi 主力", "copy_from_role": "creative",
            "model": "kimi-k2.6", "base_url": "https://api.moonshot.cn/v1",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["overwrote"] is False
        assert len(body["presets"]) == 1
        p = body["presets"][0]
        assert p["has_api_key"] is True
        assert "****" in p["api_key_masked"]
        assert p["api_key_masked"] != "sk-creative-key"  # 出参永不回明文

        # 列表读面一致
        assert client.get("/api/system/model-presets").json()["presets"][0]["name"] == "Kimi 主力"

        # 同名再存 = 覆盖
        body = client.post("/api/system/model-presets", json={
            "name": "Kimi 主力", "copy_from_role": "creative",
        }).json()
        assert body["overwrote"] is True
        assert len(body["presets"]) == 1

        # apply 到 reasoning：旧 reasoning 半态（无 Key）不触发自动存档；整卡写入含 Key
        resp = client.post(f"/api/system/model-presets/{p['id']}/apply", json={"role": "reasoning"})
        assert resp.status_code == 200
        abody = resp.json()
        assert abody["applied"]["name"] == "Kimi 主力"
        assert abody["auto_captured"] is None
        assert mc.get_llm_config()["reasoning"]["api_key"] == "sk-creative-key"
        assert mc.get_llm_config()["reasoning"]["model"] == "kimi-k2.6"

        # 纯空白名 422（schema min_length 拦不住 "   "）
        assert client.post("/api/system/model-presets", json={"name": "   "}).status_code == 422

        # 不存在的预设 apply → 404
        assert client.post("/api/system/model-presets/no-such/apply", json={"role": "creative"}).status_code == 404

        # 删除幂等，列表清空
        did = abody["presets"][0]["id"]
        assert client.delete(f"/api/system/model-presets/{did}").status_code == 200
        assert client.get("/api/system/model-presets").json()["presets"] == []
