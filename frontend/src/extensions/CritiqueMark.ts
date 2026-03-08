import { Mark, mergeAttributes } from '@tiptap/core'

export interface CritiqueMarkOptions {
  HTMLAttributes: Record<string, any>
}

declare module '@tiptap/core' {
  interface Commands<ReturnType> {
    critiqueHighlight: {
      /**
       * Set a critique highlight mark
       */
      setCritiqueHighlight: (attributes?: {
        id: string
        comment: string
        type: string
        reader_feeling: string
        suggestion: string
      }) => ReturnType
      /**
       * Unset a critique highlight mark
       */
      unsetCritiqueHighlight: () => ReturnType
    }
  }
}

export const CritiqueMark = Mark.create<CritiqueMarkOptions>({
  name: 'critiqueHighlight',

  addOptions() {
    return {
      HTMLAttributes: {},
    }
  },

  addAttributes() {
    return {
      id: {
        default: null,
        parseHTML: element => element.getAttribute('data-id'),
        renderHTML: attributes => {
          if (!attributes.id) {
            return {}
          }
          return {
            'data-id': attributes.id,
          }
        },
      },
      comment: {
        default: null,
        parseHTML: element => element.getAttribute('data-comment'),
        renderHTML: attributes => {
          if (!attributes.comment) {
            return {}
          }
          return {
            'data-comment': attributes.comment,
            title: attributes.comment, // Show comment on hover as native tooltip
          }
        },
      },
      type: {
        default: null,
        parseHTML: element => element.getAttribute('data-type'),
        renderHTML: attributes => {
          if (!attributes.type) {
            return {}
          }
          return {
            'data-type': attributes.type,
          }
        },
      },
      reader_feeling: {
        default: null,
        parseHTML: element => element.getAttribute('data-reader-feeling'),
        renderHTML: attributes => {
          if (!attributes.reader_feeling) {
            return {}
          }
          return {
            'data-reader-feeling': attributes.reader_feeling,
          }
        },
      },
      suggestion: {
        default: null,
        parseHTML: element => element.getAttribute('data-suggestion'),
        renderHTML: attributes => {
          if (!attributes.suggestion) {
            return {}
          }
          return {
            'data-suggestion': attributes.suggestion,
          }
        },
      },
    }
  },

  parseHTML() {
    return [
      {
        tag: 'mark.critique-highlight',
      },
    ]
  },

  renderHTML({ HTMLAttributes }) {
    return ['mark', mergeAttributes(this.options.HTMLAttributes, HTMLAttributes, { class: 'critique-highlight' }), 0]
  },

  addCommands() {
    return {
      setCritiqueHighlight:
        attributes =>
        ({ commands }) => {
          return commands.setMark(this.name, attributes)
        },
      unsetCritiqueHighlight:
        () =>
        ({ commands }) => {
          return commands.unsetMark(this.name)
        },
    }
  },
})
