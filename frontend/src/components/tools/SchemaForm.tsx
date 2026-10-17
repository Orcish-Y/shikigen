import { generateForm } from '@rjsf/shadcn';
import type { FormProps } from '@rjsf/core';
import { ariaDescribedByIds, getInputProps, type BaseInputTemplateProps, type FieldProps, type RJSFSchema, type WidgetProps } from '@rjsf/utils';
import { schemaValidatorFor } from '../../schema-validation';
import { Input } from '../ui/input';
import { Textarea } from '../ui/textarea';
import { JsonEditor } from './JsonEditor';

const Form = generateForm<Record<string, unknown>, RJSFSchema>();

function BaseInput({id, htmlName, value, type, schema, options, onChange, onChangeOverride,
  onBlur, onFocus, required, readonly, disabled, placeholder, rawErrors, extraProps}: BaseInputTemplateProps) {
  return <Input {...extraProps} {...getInputProps(schema, type, options)} type={schema.type === 'string' ? 'text' : type} id={id} name={htmlName || id}
    value={value ?? ''} placeholder={placeholder} required={required} readOnly={readonly} disabled={disabled}
    aria-invalid={Boolean(rawErrors?.length)} aria-describedby={ariaDescribedByIds(id)}
    onChange={onChangeOverride ?? (event => onChange(event.target.value))}
    onBlur={event => onBlur(id, event.target.value)} onFocus={event => onFocus(id, event.target.value)}/>;
}
function TextareaWidget({id, value, disabled, readonly, onChange, onBlur, onFocus}: WidgetProps) {
  return <Textarea id={id} value={value ?? ''} disabled={disabled} readOnly={readonly}
    onChange={event => onChange(event.target.value)} onBlur={event => onBlur(id,event.target.value)} onFocus={event => onFocus(id,event.target.value)}/>;
}
function FormatWidget({id,value,disabled,readonly,onChange,onBlur,onFocus,rawErrors,schema}:WidgetProps) {
  return <div className="schema-editor"><Input id={id} type="text" value={value ?? ''} disabled={disabled} readOnly={readonly}
    aria-invalid={Boolean(rawErrors?.length)} aria-describedby={ariaDescribedByIds(id)}
    onChange={event => onChange(event.target.value)} onBlur={event => onBlur(id,event.target.value)} onFocus={event => onFocus(id,event.target.value)}/>
    <span className="tool-muted">format: {schema.format}（仅作注解）</span>
  </div>;
}
function JsonSchemaField({formData, onChange, fieldPathId, schema, disabled, readonly}: FieldProps) {
  return <JsonEditor id={fieldPathId.$id} label={schema.title ?? 'JSON'} value={formData}
    disabled={disabled || readonly} emptyIsNull={fieldPathId.path.at(-1) === 'output_schema'}
    onChange={value => onChange(value,fieldPathId.path)}/>;
}
function BooleanWidget({id,value,disabled,readonly,onChange,rawErrors,label,hideLabel,required}:WidgetProps) {
  return <div className="schema-editor">{!hideLabel && <label htmlFor={id}>{label}{required && ' *'}</label>}<select id={id} className="tool-select" disabled={disabled || readonly} aria-invalid={Boolean(rawErrors?.length)}
    value={value === undefined ? '' : String(value)} onChange={event => onChange(event.target.value === '' ? undefined : event.target.value === 'true')}>
    <option value="">未提供</option><option value="true">true</option><option value="false">false</option>
  </select></div>;
}
function SelectWidget({id,value,options,disabled,readonly,onChange,rawErrors,multiple}:WidgetProps) {
  const choices=options.enumOptions ?? [];
  const indexOf=(value:unknown) => choices.findIndex(choice => JSON.stringify(choice.value) === JSON.stringify(value));
  const selected=multiple ? (Array.isArray(value) ? value.map(item => String(indexOf(item))) : [])
    : value === undefined ? '' : String(indexOf(value));
  return <select id={id} className="tool-select" multiple={multiple} value={selected} disabled={disabled || readonly}
    aria-invalid={Boolean(rawErrors?.length)} aria-describedby={ariaDescribedByIds(id)} onChange={event => {
      if (multiple) onChange([...event.target.selectedOptions].map(option => choices[Number(option.value)].value));
      else onChange(event.target.value === '' ? undefined : choices[Number(event.target.value)].value);
    }}>
    {!multiple && <option value="">未提供</option>}
    {choices.map((choice,index) => <option key={index} value={index}>{choice.label || JSON.stringify(choice.value)}</option>)}
  </select>;
}

export function SchemaForm(props: Omit<FormProps<Record<string, unknown>, RJSFSchema>, 'validator'>) {
  return <Form {...props} validator={schemaValidatorFor(props.schema)}
    noHtml5Validate templates={{...props.templates,BaseInputTemplate:BaseInput}}
    widgets={{TextareaWidget,CheckboxWidget:BooleanWidget,SelectWidget,
      DateWidget:FormatWidget,DateTimeWidget:FormatWidget,TimeWidget:FormatWidget,
      EmailWidget:FormatWidget,URLWidget:FormatWidget,FileWidget:FormatWidget,...props.widgets}}
    fields={{JsonSchema:JsonSchemaField,...props.fields}}
    experimental_defaultFormStateBehavior={{emptyObjectFields:'skipDefaults',
      arrayMinItems:{populate:'never'}, requiredBooleanDefault:'skip', constAsDefaults:'never', allOf:'skipDefaults', mergeDefaultsIntoFormData:'useFormDataIfPresent'}}/>;
}
