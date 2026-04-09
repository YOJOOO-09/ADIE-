import { useEffect, useState } from 'react'
import {
  FileText, Activity, ShieldAlert, Cpu, Settings, RefreshCw, Upload, Play, Server
} from 'lucide-react'
import axios from 'axios'

export default function App() {
  const [activeTab, setActiveTab] = useState('overview')
  const [rules, setRules] = useState([])
  const [violations, setViolations] = useState([])
  const [audit, setAudit] = useState([])
  const [loading, setLoading] = useState(false)
  const [lastSync, setLastSync] = useState(new Date().toLocaleTimeString())

  const fetchData = async () => {
    try {
      const [v, r, a] = await Promise.all([
        axios.get('/api/violations'),
        axios.get('/api/rules'),
        axios.get('/api/audit')
      ])
      // Only trigger a re-render if data actively changed (simplified optimization)
      if (JSON.stringify(v.data) !== JSON.stringify(violations)) setViolations(v.data || [])
      if (JSON.stringify(r.data) !== JSON.stringify(rules)) setRules(r.data || [])
      if (JSON.stringify(a.data) !== JSON.stringify(audit)) setAudit(a.data || [])
      
      setLastSync(new Date().toLocaleTimeString())
    } catch (e) {
      console.error(e)
    }
  }

  // Optimized Real-time Polling Engine (Every 1.5s)
  useEffect(() => {
    fetchData()
    const intv = setInterval(fetchData, 1500)
    return () => clearInterval(intv)
  }, [violations, rules, audit])

  const runE2E = async () => {
    setLoading(true)
    try {
      await axios.post('/api/run-monitor-sim')
      await fetchData()
    } catch(e) {
      console.error(e)
    }
    setLoading(false)
  }

  return (
    <div className="app-container">
      {/* Sidebar */}
      <div className="sidebar">
        <div className="brand">
          <div className="brand-icon">
             <Cpu size={18} color="white" />
          </div>
          <span>ADIE <span style={{fontWeight:500}}>CORE</span></span>
        </div>
        <div className="nav-links">
          <div className={`nav-item ${activeTab === 'overview' ? 'active' : ''}`} onClick={() => setActiveTab('overview')}>
            <Activity size={18} /> Overview
          </div>
          <div className={`nav-item ${activeTab === 'rules' ? 'active' : ''}`} onClick={() => setActiveTab('rules')}>
            <FileText size={18} /> Knowledge Base
          </div>
          <div className={`nav-item ${activeTab === 'violations' ? 'active' : ''}`} onClick={() => setActiveTab('violations')}>
            <ShieldAlert size={18} /> Compliance Violations
          </div>
          <div className={`nav-item ${activeTab === 'audit' ? 'active' : ''}`} onClick={() => setActiveTab('audit')}>
            <Settings size={18} /> Audit Logs
          </div>
        </div>
      </div>

      {/* Main Panel */}
      <div className="main-view">
        <div className="topbar">
          <h1>{activeTab.charAt(0).toUpperCase() + activeTab.slice(1)} Dashboard</h1>
          <div className="live-indicator">
            <span className="dot"></span> SYNCED {lastSync}
          </div>
        </div>
        
        <div className="content-pane fade-up">
          
          {activeTab === 'overview' && (
             <div>
                <div className="flex-header">
                   <h2>System Diagnostics</h2>
                   <button className="btn btn-brand" onClick={runE2E} disabled={loading}>
                      {loading ? <RefreshCw size={18} className="animate-spin" /> : <Play size={18} />} 
                      Run CAD Simulation
                   </button>
                </div>
                
                <div className="stats-grid">
                   <div className="glass-card stagger-1">
                      <div className="stat-val text-brand">{rules.length}</div>
                      <div className="stat-label">Active Rules</div>
                   </div>
                   <div className="glass-card stagger-2">
                      <div className="stat-val text-critical">{violations.length}</div>
                      <div className="stat-label">CAD Violations</div>
                   </div>
                   <div className="glass-card stagger-3">
                      <div className="stat-val text-info">{audit.length}</div>
                      <div className="stat-label">Audit Iterations</div>
                   </div>
                </div>

                <div className="glass-card stagger-4">
                   <div style={{display:'flex', alignItems:'center', gap:'16px', marginBottom:'16px'}}>
                      <Server size={24} color="var(--status-pass)"/>
                      <h3 style={{fontSize:'1.3rem', color:'white'}}>ADIE AI Pipeline Enabled</h3>
                   </div>
                   <p style={{color:'var(--text-muted)'}}>
                     The Autonomous Design Integrity Engine is running in Live Mode. 
                     Data flowing from Fusion 360 is intercepted, computed securely with PythonOCC, and streamed to this dashboard in real-time.
                   </p>
                </div>
             </div>
          )}

          {activeTab === 'rules' && (
            <div className="fade-up stagger-1">
               <div className="flex-header">
                  <h2>Extracted Knowledge</h2>
                  <button className="btn"><Upload size={18}/> Push Standards PDF</button>
               </div>
               <div className="data-table-container">
                 <table className="data-table">
                   <thead>
                     <tr>
                       <th>Rule ID</th>
                       <th>Constraint Description</th>
                       <th>Hard Limit</th>
                       <th>Fault Level</th>
                     </tr>
                   </thead>
                   <tbody>
                      {rules.map((r:any) => (
                        <tr key={r.rule_id}>
                          <td className="mono-id">{r.rule_id}</td>
                          <td>{r.rule}</td>
                          <td style={{color:'white'}}>{r.value} {r.unit}</td>
                          <td><span className={`badge ${r.severity}`}>{r.severity}</span></td>
                        </tr>
                      ))}
                      {rules.length === 0 && <tr><td colSpan={4}>No rules extracted yet. Run the Analyst Agent.</td></tr>}
                   </tbody>
                 </table>
               </div>
            </div>
          )}

          {activeTab === 'violations' && (
            <div className="fade-up stagger-1">
               <div className="flex-header">
                  <h2>Detected CAD Violations</h2>
               </div>
               <p style={{marginTop:'-16px',marginBottom:'32px', color:'var(--text-muted)'}}>Real-time geometry infringements detected over OpenCASCADE solid models.</p>
               
               <div className="data-table-container">
                 <table className="data-table">
                   <thead>
                     <tr>
                       <th>Identified Body</th>
                       <th>Rule ID</th>
                       <th>Violation Detail</th>
                       <th>State</th>
                     </tr>
                   </thead>
                   <tbody>
                      {violations.map((v:any, idx) => (
                        <tr key={idx}>
                          <td style={{color:'white'}}>{v.body_name}</td>
                          <td className="mono-id">{v.rule_id}</td>
                          <td>{v.violation_detail}</td>
                          <td><span className={`badge ${v.passed ? 'info' : 'critical'}`}>{v.passed ? 'PASS' : 'FAIL'}</span></td>
                        </tr>
                      ))}
                      {violations.length === 0 && <tr><td colSpan={4}>System is clear. No violations detected.</td></tr>}
                   </tbody>
                 </table>
               </div>
            </div>
          )}

          {activeTab === 'audit' && (
            <div className="fade-up stagger-1">
               <div className="flex-header">
                  <h2>Immutable Audit Logs</h2>
               </div>
               <p style={{marginTop:'-16px',marginBottom:'32px', color:'var(--text-muted)'}}>Decentralized history of all AI mitigations and Human-in-the-Loop approvals.</p>
               
               <div className="data-table-container">
                 <table className="data-table">
                   <thead>
                     <tr>
                       <th>Timestamp</th>
                       <th>Rule</th>
                       <th>AI Engine Recommendation</th>
                       <th>Engineer Trigger</th>
                     </tr>
                   </thead>
                   <tbody>
                      {[...audit].reverse().map((a:any, idx) => (
                        <tr key={idx}>
                          <td style={{color:'var(--text-muted)', fontSize:'0.85rem'}}>{a.timestamp}</td>
                          <td className="mono-id">{a.rule_id}</td>
                          <td style={{maxWidth:'350px', whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis'}}>{a.ai_recommendation}</td>
                          <td><span className={`badge ${a.engineer_action === 'accepted' ? 'info' : 'warning'}`}>{a.engineer_action}</span></td>
                        </tr>
                      ))}
                      {audit.length === 0 && <tr><td colSpan={4}>No logs recorded.</td></tr>}
                   </tbody>
                 </table>
               </div>
            </div>
          )}

        </div>
      </div>
    </div>
  )
}
