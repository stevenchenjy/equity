import test from 'node:test';
import assert from 'node:assert/strict';
import {uiUpdateAction} from './uiVersion';

test('changed deployed build reloads idle pages but preserves unsaved and uncertain work',()=>{
  const old='/assets/index-old.js',next='/assets/index-new.js';
  assert.equal(uiUpdateAction(old,next,false,false),'reload');
  assert.equal(uiUpdateAction(old,next,true,false),'wait');
  assert.equal(uiUpdateAction(old,next,false,true),'wait');
  assert.equal(uiUpdateAction(old,old,false,false),'none');
  for(const bad of [undefined,null,{},'', 'https://example.com/untrusted.js','/assets/not-ready.css'])assert.equal(uiUpdateAction(old,bad,false,false),'none');
  assert.equal(uiUpdateAction(null,next,false,false),'none');
});
