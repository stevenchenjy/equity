import test from 'node:test';
import assert from 'node:assert/strict';
import {renderToStaticMarkup} from 'react-dom/server';
import {CapitalActions} from './CapitalActions';
import type {Snapshot} from './domain';
const data={positions:[{ticker:'HELD'}],capital_decision:{action:'NO_NEW_POSITION',market_data_timestamp:'2026-10-02',global_blockers:['current_account_snapshot_stale'],decisions:[{ticker:'HELD',decision:'HOLD',shares:0,estimated_notional:0,reasons:['Maintain the recorded core purpose'],dependencies:[],blockers:[],order_draft:null},{ticker:'NEW',decision:'BLOCKED',shares:0,estimated_notional:0,reasons:['Company valuation incomplete'],dependencies:[],blockers:[],order_draft:null}]}} as unknown as Snapshot;
test('action precedes research and explains no new position',()=>{
 const html=renderToStaticMarkup(<CapitalActions data={data}/>);
 assert.ok(html.indexOf('今天做什么')<html.indexOf('研究背景'));assert.match(html,/买入 \/ 加仓 0 股/);assert.match(html,/持有/);assert.match(html,/Company valuation incomplete/);
});
test('missing or invalidated contract never displays a numerical buy',()=>{
 const html=renderToStaticMarkup(<CapitalActions data={{...data,capital_decision:null}}/>);
 assert.match(html,/暂无当前有效/);assert.doesNotMatch(html,/BUY LIMIT/);
});
