import { defaultSchema } from 'rehype-sanitize';
import type { Root } from 'mdast';
import type { Root as HtmlRoot } from 'hast';
import { visit } from 'unist-util-visit';

/** Capture references before URL normalisation/sanitisation; none become native URLs. */
export function remarkMessageContent() {
  return (tree: Root, file: {value: unknown}) => {
    const source = String(file.value);
    visit(tree, (node, index, parent) => {
      if (node.type === 'html' && parent && index !== undefined) {
        const text = {type:'text' as const, value:node.value};
        parent.children[index] = parent.type === 'paragraph' ? text : {type:'paragraph', children:[text]};
      } else if (node.type === 'code') {
        node.data = {...node.data, hProperties:{
          dataCode:node.value, dataLanguage:node.lang ?? '', dataMeta:node.meta ?? '',
        }};
      } else if (node.type === 'link' || node.type === 'image' || node.type === 'definition') {
        let reference = node.url;
        const raw = source.slice(node.position?.start.offset, node.position?.end.offset);
        // CommonMark unescapes \\ in destinations. Preserve explicitly written
        // Windows/UNC destinations from their source span, including definitions.
        const destination = node.type === 'definition'
          ? raw.match(/^\[[^\]]+\]:\s*(?:<([^>]+)>|(\S+))/)
          : raw.match(/\]\(\s*(?:<([^>]+)>|([^\s]+?))\s*(?:["'][^"']*["']\s*)?\)$/);
        const written = destination?.[1] ?? destination?.[2];
        if (written?.includes('\\')) reference = written;
        node.data = {...node.data, hProperties:{dataReference:reference}};
        node.url = '';
      }
    });
    const definitions = new Map<string, string>();
    visit(tree, 'definition', node => {
      const reference = (node.data?.hProperties as {dataReference?:string} | undefined)?.dataReference;
      if (reference !== undefined && !definitions.has(node.identifier)) definitions.set(node.identifier, reference);
    });
    visit(tree, (node, index, parent) => {
      if ((node.type !== 'linkReference' && node.type !== 'imageReference') || !parent || index === undefined) return;
      const reference = definitions.get(node.identifier);
      if (reference === undefined) return;
      const data = {hProperties:{dataReference:reference}};
      parent.children[index] = node.type === 'linkReference'
        ? {type:'link', url:'', children:node.children, data}
        : {type:'image', url:'', alt:node.alt, data};
    });
  };
}

export const messageSchema = {
  ...defaultSchema,
  // HTML has already become text; generated footnote IDs use a message prefix.
  clobberPrefix:'',
  attributes:{...defaultSchema.attributes,
    a:[...(defaultSchema.attributes?.a ?? []), 'dataReference'],
    img:[...(defaultSchema.attributes?.img ?? []), 'dataReference'],
    code:[...(defaultSchema.attributes?.code ?? []), 'dataCode', 'dataLanguage', 'dataMeta'],
  },
};

export function messagePrefix(identity: string) {
  return 'message-' + Array.from(identity, character => character.codePointAt(0)!.toString(16)).join('-') + '-';
}

export function rehypeFootnoteScope(prefix:string) {
  return (tree:HtmlRoot) => {
    visit(tree, 'element', node => {
      if (node.properties.id === 'footnote-label') node.properties.id = `${prefix}footnote-label`;
      if (Array.isArray(node.properties.ariaDescribedBy)) node.properties.ariaDescribedBy =
        node.properties.ariaDescribedBy.map(id => id === 'footnote-label' ? `${prefix}footnote-label` : id);
    });
  };
}

export function referenceKind(reference: string): 'web' | 'local' | 'unsupported' {
  if (/^https?:\/\//i.test(reference)) return 'web';
  if (/^[a-z]:[\\/]/i.test(reference) || /^file:/i.test(reference)) return 'local';
  if (/^[a-z][a-z0-9+.-]*:/i.test(reference) || reference.startsWith('//')) return 'unsupported';
  return reference ? 'local' : 'unsupported';
}

export function codeTitle(language: string, meta: string) {
  const filename = meta.match(/^(?:filename|file)=(?:"([^"\r\n]+)"|'([^'\r\n]+)'|(\S+))$/);
  const name = filename?.[1] ?? filename?.[2] ?? filename?.[3]
    ?? (/^[\w./\\-]+\.[\w-]+$/.test(meta) ? meta : '');
  return name ? `${name}${language ? ` · ${language}` : ''}` : language || '代码';
}
