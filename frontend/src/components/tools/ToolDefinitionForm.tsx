import { useState } from 'react';
import type { ObjectFieldTemplateProps, RJSFSchema } from '@rjsf/utils';
import { BracketsCurly, GearSix } from '@phosphor-icons/react';
import { Button } from '../ui/button';
import { SchemaForm } from './SchemaForm';

function DefinitionSections({properties}: ObjectFieldTemplateProps) {
  const structureFields = new Set(['input_schema','output_schema']);
  return <div className="tool-definition-sections">
    <section className="tool-panel" aria-label="工具配置"><header className="tool-panel-heading"><GearSix size={16}/><h2>工具配置</h2><span>HTTP</span></header>
      <div className="tool-config-fields">{properties.filter(property => !structureFields.has(property.name)).map(property =>
        <div key={property.name} className={`tool-config-field tool-field-${property.name}`}>{property.content}</div>)}</div>
    </section>
    <section className="tool-panel tool-schema-panel" aria-label="输入与输出结构"><header className="tool-panel-heading"><BracketsCurly size={16}/><h2>输入与输出结构</h2><span>JSON Schema</span></header>
      <div className="tool-schema-fields">{properties.filter(property => structureFields.has(property.name)).map(property =>
        <div key={property.name}>{property.content}</div>)}</div>
    </section>
  </div>;
}

export function ToolDefinitionForm({schema, initial, disabled = false, onSave, onEdited, formId, externalSubmit = false}: {
  schema: RJSFSchema; initial: Record<string, unknown>; disabled?: boolean;
  onSave: (value: Record<string, unknown>) => void; onEdited?: () => void;
  formId?:string; externalSubmit?:boolean;
}) {
  const [value, setValue] = useState(initial);
  return <SchemaForm className="tool-definition-form" id={formId} idPrefix="tool-config" schema={schema}
    templates={{ObjectFieldTemplate:DefinitionSections}}
    formData={value} disabled={disabled} uiSchema={{
      'ui:submitButtonOptions':{norender:externalSubmit},
      'ui:order':['display_name','name','description','kind','method','url','timeout_seconds','enabled','input_schema','output_schema'],
      kind:{'ui:widget':'hidden'}, method:{'ui:readonly':true}, description:{'ui:widget':'textarea'},
      input_schema:{'ui:field':'JsonSchema'}, output_schema:{'ui:field':'JsonSchema'},
    }} onChange={event => {setValue(event.formData ?? {}); onEdited?.();}}
    onSubmit={event => {
      const draft = {...event.formData};
      if (draft.name === '') delete draft.name;
      onSave(draft);
    }}>
    {!externalSubmit && <Button type="submit" disabled={disabled}>保存工具</Button>}
  </SchemaForm>;
}
