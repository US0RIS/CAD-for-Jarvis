import { useMemo, useState } from 'react';
import {
  Activity,
  BookOpen,
  Bot,
  Box,
  Check,
  ChevronDown,
  Code2,
  FolderOpen,
  GitBranch,
  History,
  Play,
  Search,
  Send,
  Settings,
  ShieldCheck,
  Undo2,
  Redo2,
  X,
} from 'lucide-react';

type RightTab = 'design' | 'components' | 'analysis';
type BottomTab = 'simulations' | 'notebook' | 'designs' | 'history' | 'code' | 'system';

const components = [
  { name: 'JF-0530B Push-Pull Solenoid', specs: '12V DC  ·  12N force  ·  10mm stroke', price: '$8.90', supplier: 'Amazon', match: 95, kind: 'solenoid' },
  { name: 'Songle SRD-05VDC-SL-C Relay', specs: '5V DC  ·  10A 250VAC  ·  SPDT', price: '$0.99', supplier: 'Mouser', match: 87, kind: 'relay' },
  { name: 'Raspberry Pi 4 Model B', specs: 'Quad-core 1.5GHz  ·  4GB RAM', price: '$55.00', supplier: 'Raspberry Pi', match: 92, kind: 'pi', added: true },
];

const branches = [
  { name: 'baseline', state: 'Working', tone: 'good', commits: '', protected: true },
  { name: 'solenoid-swap', state: 'Not working', tone: 'bad', commits: '2 commits' },
  { name: 'pi-control-v2', state: 'Unverified', tone: 'muted', commits: '1 commit' },
];

const bottomTabs: Array<{ id: BottomTab; label: string; icon: typeof Activity }> = [
  { id: 'simulations', label: 'SIMULATIONS', icon: Activity },
  { id: 'notebook', label: 'NOTEBOOK', icon: BookOpen },
  { id: 'designs', label: 'DESIGNS', icon: GitBranch },
  { id: 'history', label: 'HISTORY', icon: History },
  { id: 'code', label: 'CODE', icon: Code2 },
  { id: 'system', label: 'SYSTEM', icon: Settings },
];

function BranchCard({ branch }: { branch: (typeof branches)[number] }) {
  return (
    <button className={`branch-card ${branch.tone}`}>
      <span className="branch-title"><span className="status-dot" />{branch.name}</span>
      <span className="branch-meta">
        <span>{branch.state}</span>
        {branch.protected ? <span className="protected"><ShieldCheck size={11} />Protected</span> : <span>{branch.commits}</span>}
      </span>
    </button>
  );
}

function ComponentCard({ item }: { item: (typeof components)[number] }) {
  return (
    <article className="component-card">
      <div className={`component-thumb ${item.kind}`} aria-label={`${item.name} image placeholder`}>
        {item.kind === 'pi' ? 'π' : item.kind === 'relay' ? 'R' : 'S'}
      </div>
      <div className="component-copy">
        <div className="component-name-row">
          <strong>{item.name}</strong>
          <span className="match-score">{item.match}% match</span>
        </div>
        <div className="component-specs">{item.specs}</div>
        <div className="component-footer">
          <span>{item.price}</span><span>·</span><span>{item.supplier}</span>
          <button className={item.added ? 'added-button' : 'add-button'}>{item.added ? <><Check size={12} />Added</> : 'Add'}</button>
        </div>
      </div>
    </article>
  );
}

function CodePanel() {
  return (
    <div className="code-panel">
      <div className="file-tree">
        <div className="workspace-title">◈ Raspberry Pi (solenoid-swap) <span className="live-dot" /></div>
        <div className="tree-folder">⌄ 📁 src</div>
        <button className="tree-file active">main.py</button>
        <button className="tree-file">latch_control.py</button>
        <button className="tree-file">motor_driver.py</button>
        <button className="tree-file">sensors.py</button>
        <div className="tree-folder">⌄ 📁 config</div>
        <button className="tree-file">config.json</button>
        <button className="tree-file">README.md</button>
      </div>
      <div className="editor-area">
        <div className="editor-toolbar"><span>🐍 main.py</span><span className="editor-actions">Python ▾ &nbsp;&nbsp; <b>Save</b> &nbsp; Check &nbsp; Ask Qwen &nbsp; Branch Code</span></div>
        <pre className="editor-code"><code>{`import RPi.GPIO as GPIO\nimport time\n\nSOLENOID_PIN = 17\nLIMIT_SWITCH_PIN = 27\n\nGPIO.setmode(GPIO.BCM)\nGPIO.setup(SOLENOID_PIN, GPIO.OUT, initial=GPIO.LOW)\n\ndef is_latch_closed():\n    return GPIO.input(LIMIT_SWITCH_PIN) == GPIO.LOW`}</code></pre>
      </div>
      <div className="run-output">
        <div className="run-title">Run / Output</div>
        <div>[+] Connected to Raspberry Pi (local)</div>
        <div>[+] Python 3.11.2</div>
        <div>[+] Ready. Use Run to test the module.</div>
        <button><Play size={12} />Run</button>
      </div>
    </div>
  );
}

export default function App() {
  const [rightTab, setRightTab] = useState<RightTab>('components');
  const [bottomTab, setBottomTab] = useState<BottomTab>('code');
  const [explode, setExplode] = useState(45);
  const [message, setMessage] = useState('');
  const [applyEdits, setApplyEdits] = useState(true);
  const [sentMessages, setSentMessages] = useState<string[]>([]);

  const conversation = useMemo(() => [
    'Branch from the known-good design, swap in a 12V solenoid, and open the Raspberry Pi code workspace.',
    ...sentMessages,
  ], [sentMessages]);

  function send() {
    const text = message.trim();
    if (!text) return;
    setSentMessages((items) => [...items, text]);
    setMessage('');
  }

  return (
    <main className="forge-shell">
      <aside className="copilot-rail">
        <header className="brand-block">
          <div className="brand-mark">A</div>
          <div><h1>ForgeCAD</h1><span>AI Engineering Studio</span></div>
        </header>
        <div className="runtime-banner"><Check size={15} /><div><strong>Local engineering copilot is online</strong><span>All design data stays on your machine.</span></div></div>
        <div className="model-row"><Bot size={15} /><span>qwen3:8b</span><ChevronDown size={14} /><span className="local-badge">LOCAL</span><Settings size={15} /></div>
        <section className="conversation">
          {conversation.map((text, i) => <div className="message" key={`${i}-${text}`}><div className="avatar">{i === 0 ? 'Y' : 'Y'}</div><div><div className="message-label">You <span>10:21 AM</span></div><p>{text}</p></div></div>)}
          <div className="message agent"><div className="avatar forge">A</div><div><div className="message-label">ForgeCAD <span>10:21 AM</span></div><p>I've created a new child branch <b>solenoid-swap</b>, selected a compatible 12V push-pull solenoid, and opened the Raspberry Pi programmable component workspace.</p><ul><li>Created branch: solenoid-swap</li><li>Selected solenoid: JF-0530B (12V)</li><li>Opened code workspace (Raspberry Pi)</li></ul></div></div>
        </section>
        <div className="quick-actions"><button>Explain selected part</button><button>Review design</button><button>Next test</button></div>
        <div className="composer">
          <textarea value={message} onChange={(e) => setMessage(e.target.value)} placeholder="Describe your engineering task…" />
          <div className="composer-footer"><button className="clip">↗</button><label><input type="checkbox" checked={applyEdits} onChange={(e) => setApplyEdits(e.target.checked)} />Apply edits</label><button className="send" onClick={send} aria-label="Send engineering request"><Send size={18} /></button></div>
        </div>
      </aside>

      <section className="workspace">
        <header className="project-toolbar">
          <div className="project-title">Adaptive Latch Assembly <ChevronDown size={14} /></div>
          <button className="branch-select"><GitBranch size={14} />main<ChevronDown size={13} /></button>
          <button className="icon-button"><Undo2 size={16} /></button><button className="icon-button"><Redo2 size={16} /></button>
          <div className="toolbar-spacer" />
          <button className="toolbar-button">⇧&nbsp; Import STEP</button>
          <button className="toolbar-button"><FolderOpen size={15} />Project</button>
          <button className="dynamics-button"><Play size={15} />Dynamics</button>
        </header>

        <section className="lineage-strip">
          <span className="lineage-label">Design lineage⌄</span>
          <div className="lineage-flow">
            {branches.map((b, i) => <div className="lineage-item" key={b.name}><BranchCard branch={b} />{i < branches.length - 1 && <span className="lineage-arrow">→</span>}</div>)}
          </div>
          <select><option>Design status: All</option></select>
          <label className="verified-toggle"><input type="checkbox" defaultChecked />Works in real life</label>
          <button className="toolbar-button">Compare to working</button>
        </section>

        <section className="main-stage">
          <div className="viewport-panel">
            <div className="viewport-toolbar">
              <button className="active">✣ Move</button><button>↻ Rotate</button><button>↗ Scale</button><span className="sep" /><button>⛶ Fit</button><button>◇ Iso</button><button>⊙ Top</button><button>▣ Front</button><button>▣ Right</button><span className="sep" /><button>◉ Auto rotate</button><button>⌖ Isolate</button><button>◌ Hide</button><button>◎ Show all</button>
            </div>
            <div className="scene-host">
              <div className="scene-grid" />
              <div className="scene-placeholder"><Box size={58} /><strong>SceneController mount</strong><span>Photorealistic GLB/PBR assembly renders here</span></div>
              <div className="selected-card"><button className="close"><X size={13} /></button><div className="selected-thumb">π</div><strong>Raspberry Pi 4 Model B <span className="live-dot" /></strong><dl><dt>Role</dt><dd>Controller / Edge Compute</dd><dt>Mass</dt><dd>46 g</dd><dt>Power draw</dt><dd>2–6 W (5V)</dd><dt>Software</dt><dd className="link">./code (attached)</dd></dl></div>
              <div className="axis">Z<br/><span>X&nbsp;&nbsp;&nbsp;Y</span></div>
              <div className="explode-control"><div><span>Explode</span><b>{explode}%</b></div><input type="range" min="0" max="100" value={explode} onChange={(e) => setExplode(Number(e.target.value))} /></div>
            </div>
          </div>

          <aside className="engineering-rail">
            <div className="rail-tabs">
              {(['design', 'components', 'analysis'] as RightTab[]).map((tab) => <button key={tab} className={rightTab === tab ? 'active' : ''} onClick={() => setRightTab(tab)}>{tab[0].toUpperCase() + tab.slice(1)}</button>)}
            </div>
            {rightTab === 'components' ? <div className="component-library"><h2>Real component library</h2><p>Actual parts from real suppliers. Buildable designs.</p><div className="search-box"><Search size={15} /><input defaultValue="solenoid" /><button>☷</button></div><div className="filter-row"><button>Category&nbsp; All⌄</button><button>Voltage&nbsp; Any⌄</button><button>Supplier&nbsp; Any⌄</button></div><div className="results-meta"><span>12 results</span><span>Sort: Relevance⌄</span></div>{components.map((item) => <ComponentCard key={item.name} item={item} />)}<div className="campaign-card"><div className="campaign-title">⌬ <div><strong>Autonomous engineering campaign</strong><span>Let AI explore, simulate, and improve this design.</span></div></div><ul><li>Parameter optimizer (multi-objective)</li><li>Generate and test design variants</li><li>Validate against real-world constraints</li></ul><button>Start engineering campaign →</button></div></div> : <div className="rail-empty"><strong>{rightTab === 'design' ? 'Design inspector' : 'Analysis workspace'}</strong><span>Backend-connected v2 panel mounts here.</span></div>}
          </aside>
        </section>

        <section className="bottom-dock">
          <nav>{bottomTabs.map(({ id, label, icon: Icon }) => <button key={id} className={bottomTab === id ? 'active' : ''} onClick={() => setBottomTab(id)}><Icon size={13} />{label}</button>)}</nav>
          <div className="dock-content">{bottomTab === 'code' ? <CodePanel /> : <div className="dock-placeholder"><strong>{bottomTab.toUpperCase()}</strong><span>v2 panel contract is defined; implementation mounts here.</span></div>}</div>
        </section>
      </section>
    </main>
  );
}
