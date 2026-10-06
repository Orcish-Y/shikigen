import test from 'node:test';
import assert from 'node:assert/strict';
import { WorkspaceFileOpening } from '../src/workspace-file-open.ts';

const intent = {request_id:'intent-1', startup_id:'startup-1', workspace_id:'workspace-1', workspace_root:'C:\\work',
  resource_id:'resource-1', absolute_path:'C:\\work\\report.txt', relative_path:'report.txt', name:'report.txt',
  kind:'file', mime_type:'text/plain', size:12, modified_at:'2026-10-06T00:00:00Z', version:'version-1',can_preview:false};
test('file click prepares metadata, cancellation discards it without opening', async () => {
  const commands = [];
  const opening = new WorkspaceFileOpening('startup-1', async (command, args) => {
    commands.push([command,args]); return command === 'prepare_workspace_file_open' ? intent : true;
  });
  await opening.prepareFileOpen('report.txt', 'message-1:0');
  assert.equal(opening.view.phase,'prepared');
  assert.equal(opening.view.intent.absolute_path,'C:\\work\\report.txt');
  opening.closeFileOpen(); await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(commands,[['prepare_workspace_file_open',{startupId:'startup-1',path:'report.txt'}],
    ['discard_prepared_workspace_file',{requestId:'intent-1'}]]);
  assert.equal(opening.view.phase,'idle');
});

test('confirm opens only the prepared ID once, never passes a path/address/root', async () => {
  const commands=[]; let finishOpen;
  const opening = new WorkspaceFileOpening('startup-1', async (command,args) => {
    commands.push([command,args]);
    if (command === 'prepare_workspace_file_open') return intent;
    if (command === 'open_prepared_workspace_file') return new Promise(resolve => finishOpen=resolve);
    return true;
  });
  await opening.prepareFileOpen('report.txt', 'message-1:0');
  const invocationPromise = opening.confirmFileOpen();
  await opening.confirmFileOpen(); await opening.prepareFileOpen('other.txt', 'message-1:0');
  assert.equal(opening.view.phase,'opening');
  assert.deepEqual(commands[1],['open_prepared_workspace_file',{requestId:'intent-1'}]);
  assert.equal(commands.length,2);
  finishOpen(true); await invocationPromise;
  assert.equal(opening.view.phase,'accepted');
  await opening.confirmFileOpen(); assert.equal(commands.length,2);
});

test('closing an unfinished preparation discards an ignored-abort late intent and cannot reopen', async () => {
  const commands=[]; let finishPrepare;
  const opening = new WorkspaceFileOpening('startup-1', async (command,args) => {
    commands.push([command,args]);
    return command === 'prepare_workspace_file_open' ? new Promise(resolve => finishPrepare=resolve) : true;
  });
  const invocationPromise = opening.prepareFileOpen('report.txt', 'message-1:0');
  opening.disposeFileOpening(); finishPrepare(intent); await invocationPromise;
  await opening.confirmFileOpen(); await opening.prepareFileOpen('report.txt', 'message-1:0');
  assert.equal(opening.view.phase,'idle');
  assert.deepEqual(commands.map(([command]) => command),['prepare_workspace_file_open','discard_prepared_workspace_file']);
});

test('closing an unfinished open filters late acceptance without automatic retry', async () => {
  let finishOpen; const commands=[];
  const opening = new WorkspaceFileOpening('startup-1', async (command,args) => {
    commands.push([command,args]);
    if(command==='prepare_workspace_file_open') return intent;
    if(command==='open_prepared_workspace_file') return new Promise(resolve => finishOpen=resolve);
    return true;
  });
  await opening.prepareFileOpen('report.txt', 'message-1:0'); const invocationPromise=opening.confirmFileOpen();
  opening.closeFileOpen(); finishOpen(true); await invocationPromise;
  assert.equal(opening.view.phase,'idle');
  assert.deepEqual(commands.map(([command]) => command),['prepare_workspace_file_open','open_prepared_workspace_file','discard_prepared_workspace_file']);
});

test('changed target failure retains actual reason and needs a new preparation plus confirmation', async () => {
  let preparationCount=0; const commands=[];
  const opening = new WorkspaceFileOpening('startup-1', async (command,args) => {
    commands.push([command,args]);
    if(command==='prepare_workspace_file_open') return {...intent,request_id:`intent-${++preparationCount}`,version:`version-${preparationCount}`};
    if(command==='open_prepared_workspace_file' && args.requestId==='intent-1') throw {code:'changed_file_target',message:'文件版本已变化'};
    return true;
  });
  await opening.prepareFileOpen('report.txt', 'message-1:0'); await opening.confirmFileOpen();
  assert.equal(opening.view.phase,'error'); assert.equal(opening.view.error,'文件版本已变化');
  await opening.confirmFileOpen(); assert.equal(commands.length,2);
  await opening.prepareFileOpen('report.txt', 'message-1:0');
  assert.equal(opening.view.phase,'prepared'); assert.equal(opening.view.intent.version,'version-2');
  assert.equal(commands.filter(([command])=>command==='open_prepared_workspace_file').length,1);
  await opening.confirmFileOpen(); assert.equal(opening.view.phase,'accepted');
});

test('invalid host metadata is read-only failure and any issued intent is revoked', async () => {
  for (const invalidMetadata of [{startup_id:'old'}, {kind:'directory'}, {size:-1}, {workspace_root:''}, {version:''}, {mime_type:42}, {modified_at:'invalid'}]) {
    const commands=[];
    const opening = new WorkspaceFileOpening('startup-1', async (command,args) => {
      commands.push([command,args]); return command==='prepare_workspace_file_open' ? {...intent,...invalidMetadata} : true;
    });
    await opening.prepareFileOpen('report.txt', 'message-1:0'); await opening.confirmFileOpen();
    assert.equal(opening.view.phase,'error');
    assert.match(opening.view.error,/元数据无效/);
    assert.deepEqual(commands.map(([command])=>command),['prepare_workspace_file_open','discard_prepared_workspace_file']);
  }
});

test('system rejection or unknown acceptance consumes the UI confirmation without a second open', async () => {
  for(const response of [false,undefined,{error:true}]) {
    let openCount=0;
    const opening = new WorkspaceFileOpening('startup-1',async command => {
      if(command==='prepare_workspace_file_open') return intent;
      if(command==='open_prepared_workspace_file') {++openCount; return response;} return true;
    });
    await opening.prepareFileOpen('report.txt', 'message-1:0'); await opening.confirmFileOpen(); await opening.confirmFileOpen();
    assert.equal(openCount,1); assert.equal(opening.view.phase,'error'); assert.match(opening.view.error,/不会自动再打开/);
  }
});
