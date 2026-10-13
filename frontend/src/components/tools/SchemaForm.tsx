import { generateForm } from '@rjsf/shadcn';
import type { FormProps } from '@rjsf/core';
import { customizeValidator } from '@rjsf/validator-ajv8';
import { ariaDescribedByIds, getInputProps, type BaseInputTemplateProps, type FieldProps, type RJSFSchema, type WidgetProps } from '@rjsf/utils';
import { useState } from 'react';
import { Input } from '../ui/input';
import { Textarea } from '../ui/textarea';

const validator = customizeValidator({ajvOptionsOverrides:{validateFormats:false, coerceTypes:false, useDefaults:false, removeAdditional:false}});
const Form = generateForm<Record<string, unknown>, RJSFSchema>();

function BaseInput({id, htmlName, value, type, schema, options, onChange, onChangeOverride,
  onBlur, onFocus, required, readonly, disabled, placeholder, rawErrors, extraProps}: BaseInputTemplateProps) {
  return <Input {...extraProps} {...getInputProps(schema, type, options)} id={id} name={htmlName || id}
    value={value ?? ''} placeholder={placeholder} required={required} readOnly={readonly} disabled={disabled}
    aria-invalid={Boolean(rawErrors?.length)} aria-describedby={ariaDescribedByIds(id)}
    onChange={onChangeOverride ?? (event => onChange(event.target.value))}
    onBlur={event => onBlur(id, event.target.value)} onFocus={event => onFocus(id, event.target.value)}/>;
}
function TextareaWidget({id, value, disabled, readonly, onChange, onBlur, onFocus}: WidgetProps) {
  return <Textarea id={id} value={value ?? ''} disabled={disabled} readOnly={readonly}
    onChange={event => onChange(event.target.value)} onBlur={event => onBlur(id,event.target.value)} onFocus={event => onFocus(id,event.target.value)}/>;
}
function JsonSchemaField({formData, onChange, fieldPathId, schema, disabled, readonly}: FieldProps) {
  const value = typeof formData === 'string' ? formData : JSON.stringify(formData ?? null, null, 2);
  const [error, setError] = useState<string | null>(null);
  return <div className="schema-editor">
    <label htmlFor={fieldPathId.$id}>{schema.title}</label>
    <Textarea id={fieldPathId.$id} value={value} disabled={disabled} readOnly={readonly} rows={5}
      aria-invalid={Boolean(error)} onChange={event => {
        const text = event.target.value;
        try { onChange(JSON.parse(text), fieldPathId.path); setError(null); }
        catch { onChange(text, fieldPathId.path); setError('JSON 无效，请修正后保存'); }
      }}/>
    {error && <p role="alert">{error}</p>}
  </div>;
}

export function SchemaForm(props: Omit<FormProps<Record<string, unknown>, RJSFSchema>, 'validator'>) {
  return <Form {...props} validator={validator}
    noHtml5Validate templates={{...props.templates,BaseInputTemplate:BaseInput}}
    widgets={{TextareaWidget}} fields={{JsonSchema:JsonSchemaField}}
    experimental_defaultFormStateBehavior={{emptyObjectFields:'skipDefaults',
      arrayMinItems:{populate:'never'}, constAsDefaults:'never', allOf:'skipDefaults', mergeDefaultsIntoFormData:'useFormDataIfPresent'}}/>;
}
