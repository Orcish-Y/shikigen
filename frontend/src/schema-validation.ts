import {customizeValidator} from '@rjsf/validator-ajv8';
import type {RJSFSchema} from '@rjsf/utils';
import Ajv2020 from 'ajv/dist/2020.js';

const options={ajvOptionsOverrides:{validateFormats:false,coerceTypes:false,useDefaults:false,removeAdditional:false,multipleOfPrecision:undefined},ajvFormatOptions:false as const};
const validator=customizeValidator(options);
const validator2020=customizeValidator({...options,AjvClass:Ajv2020});

export function schemaValidatorFor(schema:RJSFSchema) {
  return schema.$schema === 'https://json-schema.org/draft/2020-12/schema' ? validator2020 : validator;
}
