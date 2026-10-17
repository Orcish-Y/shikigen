import {useEffect, useRef} from 'react';
import {Annotation, Compartment, EditorState, Transaction} from '@codemirror/state';
import {EditorView, keymap} from '@codemirror/view';
import {indentWithTab} from '@codemirror/commands';
import {setDiagnostics} from '@codemirror/lint';
import {python} from '@codemirror/lang-python';
import {indentUnit} from '@codemirror/language';
import {basicSetup} from 'codemirror';
import {ariaDescribedByIds, type WidgetProps} from '@rjsf/utils';
import type {PythonDiagnostic} from '../../python-source';

const externalValue = Annotation.define<boolean>();

export function PythonSourceEditor(props:WidgetProps) {
  const host = useRef<HTMLDivElement>(null);
  const editor = useRef<{view:EditorView; attributes:Compartment; access:Compartment} | null>(null);
  const latest = useRef(props);
  latest.current = props;
  const {id, value, disabled, readonly, required, label, schema, rawErrors, registry} = props;
  const diagnostics:PythonDiagnostic[] = registry.formContext?.pythonAnalysis?.diagnostics ?? [];

  useEffect(() => {
    const attributes = new Compartment();
    const access = new Compartment();
    const view = new EditorView({parent:host.current!, state:EditorState.create({
      doc:typeof latest.current.value === 'string' ? latest.current.value : '',
      extensions:[basicSetup, python(), indentUnit.of('    '), EditorState.tabSize.of(4),
        keymap.of([indentWithTab]), attributes.of([]), access.of([]),
        EditorView.updateListener.of(update => {
          if (update.docChanged && !update.transactions.some(transaction => transaction.annotation(externalValue)))
            latest.current.onChange(update.state.doc.toString());
        }),
        EditorView.domEventHandlers({
          focus:(_event, current) => latest.current.onFocus(latest.current.id, current.state.doc.toString()),
          blur:(_event, current) => latest.current.onBlur(latest.current.id, current.state.doc.toString()),
        }),
      ],
    })});
    editor.current = {view, attributes, access};
    return () => {editor.current = null; view.destroy();};
  }, []);

  useEffect(() => {
    const current = editor.current!;
    current.view.dispatch({effects:[
      current.attributes.reconfigure(EditorView.contentAttributes.of({
        id, 'aria-label':label || schema.title || 'Python 源码',
        'aria-describedby':ariaDescribedByIds(id), 'aria-multiline':'true',
        'aria-required':String(Boolean(required)), 'aria-readonly':String(Boolean(readonly || disabled)),
        'aria-disabled':String(Boolean(disabled)), 'aria-invalid':String(Boolean(rawErrors?.length || diagnostics.length)),
        tabindex:disabled ? '-1' : '0', spellcheck:'false',
      })),
      current.access.reconfigure([EditorState.readOnly.of(Boolean(readonly || disabled)), EditorView.editable.of(!disabled)]),
    ]});
  }, [id, label, schema.title, required, readonly, disabled, rawErrors?.length, diagnostics.length]);

  useEffect(() => {
    const view = editor.current!.view;
    const source = typeof value === 'string' ? value : '';
    const document=view.state.toText(source);
    if (view.state.doc.eq(document)) return;
    const {anchor, head} = view.state.selection.main;
    view.dispatch({changes:{from:0, to:view.state.doc.length, insert:document},
      selection:{anchor:Math.min(anchor, document.length), head:Math.min(head, document.length)},
      annotations:[externalValue.of(true), Transaction.addToHistory.of(false)],
    });
  }, [value]);

  useEffect(() => {
    const view = editor.current!.view;
    const source=typeof value === 'string' ? value : '';
    // Lezer offsets refer to the original string; CodeMirror stores CRLF as
    // one document line break. Both otherwise use UTF-16 offsets.
    const offset=(position:number) => Math.min(view.state.toText(source.slice(0,position)).length,view.state.doc.length);
    view.dispatch(setDiagnostics(view.state, diagnostics.map(({from, to, message, severity, code}) => ({
      from:offset(from), to:offset(to),
      severity, message:`${code}: ${message}`,
    }))));
  }, [diagnostics,value]);

  return <div className="tool-python-editor" ref={host}/>;
}
