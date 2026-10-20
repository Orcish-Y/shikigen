import {BackendRequestError} from './backend-client';

/** A known rejection means the write did not commit. Other failures stay uncertain. */
export function saveWasRejected(failure:unknown):boolean {
  if (!(failure instanceof BackendRequestError)) return false;
  if (failure.status === 409 || failure.status === 422) return true;
  try {
    const code=JSON.parse(failure.detail).detail?.code;
    return ['config_read','config_write','config_source','python_source_empty','python_source_read',
      'python_source_write','not_found','definition_invalid','connection_invalid','read_only'].includes(code);
  } catch {return false;}
}
