'use client';

import React, { useState, useEffect } from 'react';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface User {
  id: string;
  email: string;
  role: string;
  customer_id?: string;
}

interface Message {
  id: string;
  actor_type: string;
  content: string;
  created_at: string;
}

interface Approval {
  id: string;
  ticket_id: string;
  action_type: string;
  proposal_payload: any;
  proposal_hash: string;
  status: string;
  reviewer_comment?: string;
  created_at: string;
  expires_at: string;
}

interface HandoffItem {
  id: string;
  ticket_id: string;
  reason_code: string;
  summary: string;
  status: string;
  created_at: string;
}

interface AuditItem {
  id: string;
  event_type: string;
  actor_type: string;
  resource_type: string;
  resource_id: string;
  metadata_redacted: any;
  created_at: string;
}

export default function Home() {
  const [token, setToken] = useState<string | null>(null);
  const [authMode, setAuthMode] = useState<'login' | 'register'>('login');
  const [authName, setAuthName] = useState('');
  const [authEmail, setAuthEmail] = useState('');
  const [authPassword, setAuthPassword] = useState('');
  const [authError, setAuthError] = useState('');
  const [notice, setNotice] = useState('');
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [activeTab, setActiveTab] = useState<'chat' | 'approvals' | 'handoffs' | 'audit'>('chat');

  // Customer Chat State
  const [conversationId, setConversationId] = useState<string>('');
  const [ticketId, setTicketId] = useState<string>('');
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputMessage, setInputMessage] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  // Reviewer State
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [handoffs, setHandoffs] = useState<HandoffItem[]>([]);
  const [auditEvents, setAuditEvents] = useState<AuditItem[]>([]);
  const [decisionComment, setDecisionComment] = useState('');
  const [selectedTicketForAudit, setSelectedTicketForAudit] = useState('');

  // Authenticate against the API; customer registration creates a real database account.
  const handleAuth = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true); setAuthError('');
    try {
      const registering = authMode === 'register';
      const res = await fetch(`${API_BASE}/api/v1/auth/${registering ? 'register' : 'token'}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(registering ? { name: authName, email: authEmail, password: authPassword } : { email: authEmail, password: authPassword }),
      });
      if (!res.ok) { const error = await res.json().catch(() => ({})); throw new Error(error.detail || 'Unable to authenticate. Check your details and try again.'); }
      const data = await res.json();
      const meRes = await fetch(`${API_BASE}/api/v1/auth/me`, { headers: { Authorization: `Bearer ${data.access_token}` } });
      if (!meRes.ok) throw new Error('Your account could not be loaded. Please sign in again.');
      const meData = await meRes.json();
      sessionStorage.setItem('agent-v-token', data.access_token);
      setToken(data.access_token); setCurrentUser(meData); setActiveTab(meData.role === 'customer' ? 'chat' : meData.role === 'auditor' ? 'audit' : 'approvals'); setAuthError('');
    } catch (err: any) { setAuthError(err.message || 'Something went wrong. Please try again.'); }
    finally { setIsLoading(false); }
  };

  useEffect(() => {
    const savedToken = sessionStorage.getItem('agent-v-token');
    if (!savedToken) return;
    fetch(`${API_BASE}/api/v1/auth/me`, { headers: { Authorization: `Bearer ${savedToken}` } })
      .then(async (res) => { if (!res.ok) throw new Error('Session expired'); return res.json(); })
      .then((user) => { setToken(savedToken); setCurrentUser(user); setActiveTab(user.role === 'customer' ? 'chat' : user.role === 'auditor' ? 'audit' : 'approvals'); })
      .catch(() => sessionStorage.removeItem('agent-v-token'));
  }, []);

  const handleLogout = () => { sessionStorage.removeItem('agent-v-token'); setToken(null); setCurrentUser(null); setMessages([]); };

  // Load the signed-in customer's latest ticket, or open their first support conversation.
  const loadTicketMessages = async () => {
    if (!token) return;
    try {
      const ticketsRes = await fetch(`${API_BASE}/api/v1/tickets`, { headers: { Authorization: `Bearer ${token}` } });
      if (!ticketsRes.ok) throw new Error('Could not load your conversations.');
      const tickets = await ticketsRes.json();
      const ticket = tickets[0];
      if (!ticket) {
        const createdRes = await fetch(`${API_BASE}/api/v1/conversations`, {
          method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
          body: JSON.stringify({ subject: 'Customer Support Inquiry' }),
        });
        if (!createdRes.ok) throw new Error('Could not start a support conversation.');
        const conv = await createdRes.json();
        setTicketId(conv.ticket_id); setConversationId(conv.id); setMessages(conv.messages || []);
        return;
      }
      setTicketId(ticket.id);
      const detailRes = await fetch(`${API_BASE}/api/v1/tickets/${ticket.id}`, { headers: { Authorization: `Bearer ${token}` } });
      if (!detailRes.ok) throw new Error('Could not open your support conversation.');
      const details = await detailRes.json();
      let conv = details.conversations?.[0];
      if (!conv) {
        const createdRes = await fetch(`${API_BASE}/api/v1/conversations`, {
          method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
          body: JSON.stringify({ ticket_id: ticket.id, subject: ticket.subject }),
        });
        if (!createdRes.ok) throw new Error('Could not start a support conversation.');
        conv = await createdRes.json();
      }
      setConversationId(conv.id); setMessages(conv.messages || []);
    } catch (err: any) { setNotice(err.message || 'Unable to load this conversation.'); }
  };

  // Send message
  const handleSendMessage = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!inputMessage.trim() || !token || !conversationId) return;

    const userText = inputMessage;
    setInputMessage('');
    setIsLoading(true);

    const tempMsg: Message = {
      id: `tmp-${Date.now()}`,
      actor_type: 'customer',
      content: userText,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, tempMsg]);

    try {
      const res = await fetch(`${API_BASE}/api/v1/conversations/${conversationId}/messages`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ content: userText }),
      });
      if (!res.ok) throw new Error('Failed to send message');
      const agentMsg = await res.json();
      setMessages((prev) => [...prev, agentMsg]);
    } catch (err: any) {
      alert(err.message);
    } finally {
      setIsLoading(false);
    }
  };

  // Reviewer: Load approvals
  const loadApprovals = async () => {
    if (!token) return;
    try {
      const res = await fetch(`${API_BASE}/api/v1/approvals`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const data = await res.json();
        setApprovals(data);
      }
    } catch (err) {
      console.error(err);
    }
  };

  // Reviewer: Decide approval
  const handleDecision = async (approvalId: string, decision: 'APPROVE' | 'REJECT') => {
    if (!token) return;
    setIsLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/v1/approvals/${approvalId}/decision`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ decision, comment: decisionComment }),
      });
      if (!res.ok) {
        const error = await res.json();
        throw new Error(error.detail || 'Decision execution failed');
      }
      alert(`Action ${decision}D successfully!`);
      setDecisionComment('');
      await loadApprovals();
    } catch (err: any) {
      alert(`Decision error: ${err.message}`);
    } finally {
      setIsLoading(false);
    }
  };

  // Reviewer: Load handoffs
  const loadHandoffs = async () => {
    if (!token) return;
    try {
      const res = await fetch(`${API_BASE}/api/v1/handoffs`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const data = await res.json();
        setHandoffs(data);
      }
    } catch (err) {
      console.error(err);
    }
  };

  // Auditor: Load audit events
  const loadAudit = async () => {
    if (!token || !selectedTicketForAudit) return;
    try {
      const res = await fetch(`${API_BASE}/api/v1/audit/${selectedTicketForAudit}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const data = await res.json();
        setAuditEvents(data);
      }
    } catch (err) {
      console.error(err);
    }
  };

  useEffect(() => {
    if (token) {
      if (activeTab === 'chat') loadTicketMessages();
      if (activeTab === 'approvals') loadApprovals();
      if (activeTab === 'handoffs') loadHandoffs();
      if (activeTab === 'audit') loadAudit();
    }
  }, [token, activeTab]);

  return (
    <div>
      <header>
        <div className="brand"><span>Agent V</span><span className="badge badge-blue">Support workspace</span></div>
        <div>
          {currentUser ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <span style={{ fontSize: '0.875rem', color: 'var(--text-secondary)' }}>
                {currentUser.email} ({currentUser.role})
              </span>
              <button className="btn btn-outline" onClick={handleLogout}>
                Logout
              </button>
            </div>
          ) : null}
        </div>
      </header>

      <main className="container">
        {notice && <div className="notice" role="status">{notice}<button onClick={() => setNotice('')} aria-label="Dismiss">x</button></div>}
        {currentUser ? (
          <div>
            <div className="tabs">
              {currentUser.role === 'customer' && (
              <button
                className={`tab ${activeTab === 'chat' ? 'active' : ''}`}
                onClick={() => setActiveTab('chat')}
              >Customer Chat
              </button>
              )}
              {['reviewer', 'admin', 'support_agent', 'auditor'].includes(currentUser.role) && (
                <>
                  <button
                    className={`tab ${activeTab === 'approvals' ? 'active' : ''}`}
                    onClick={() => setActiveTab('approvals')}
                  >Reviewer Queue ({approvals.filter(a => a.status === 'PENDING').length})
                  </button>
                  <button
                    className={`tab ${activeTab === 'handoffs' ? 'active' : ''}`}
                    onClick={() => setActiveTab('handoffs')}
                  >Human Handoff Queue
                  </button>
                  <button
                    className={`tab ${activeTab === 'audit' ? 'active' : ''}`}
                    onClick={() => setActiveTab('audit')}
                  >Audit Trail
                  </button>
                </>
              )}
            </div>

            {/* TAB: Customer Chat */}
            {activeTab === 'chat' && (
              <div className="card">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                  <h3>Customer Support Conversation</h3>
                  <span className="badge badge-green">Ticket: {ticketId}</span>
                </div>

                <div style={{ marginBottom: 12, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  <button
                    className="btn btn-outline"
                    onClick={() => setInputMessage('What is my subscription plan status?')}
                  >
                    Check subscription
                  </button>
                  <button
                    className="btn btn-outline"
                    onClick={() => setInputMessage('I have a question about a recent charge.')}
                  >
                    Ask about a recent charge
                  </button>
                  <button
                    className="btn btn-outline"
                    onClick={() => setInputMessage('I need help with my subscription.')}
                  >
                    Subscription help
                  </button>
                  <button
                    className="btn btn-outline"
                    onClick={() => setInputMessage('I need to update my contact information.')}
                  >
                    Update contact details
                  </button>
                  <button
                    className="btn btn-outline"
                    onClick={() => setInputMessage('I would like to speak with a support specialist.')}
                  >
                    Talk to a person
                  </button>
                </div>

                <div className="chat-box">
                  <div className="chat-messages">
                    {messages.length === 0 && <div className="chat-empty"><div className="empty-icon">A</div><h3>How can we help?</h3><p>Send a message and our support assistant will take it from there.</p></div>}
                    {messages.map((m) => (
                      <div
                        key={m.id}
                        className={`message-bubble ${m.actor_type === 'customer' ? 'msg-customer' : 'msg-agent'}`}
                      >
                        <div style={{ fontSize: '0.75rem', opacity: 0.8, marginBottom: 4 }}>
                          {m.actor_type.toUpperCase()}
                        </div>
                        {m.content}
                      </div>
                    ))}
                    {isLoading && (
                      <div className="message-bubble msg-agent" style={{ fontStyle: 'italic', opacity: 0.7 }}>
                        Agent is reasoning and validating policies...
                      </div>
                    )}
                  </div>
                  <form className="chat-input-bar" onSubmit={handleSendMessage}>
                    <input
                      type="text"
                      className="chat-input"
                      placeholder="Type your question or request..."
                      value={inputMessage}
                      onChange={(e) => setInputMessage(e.target.value)}
                      disabled={isLoading}
                    />
                    <button type="submit" className="btn btn-primary" disabled={isLoading}>
                      Send
                    </button>
                  </form>
                </div>
              </div>
            )}

            {/* TAB: Reviewer Approval Queue */}
            {activeTab === 'approvals' && (
              <div className="card">
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
                  <h3>High-Risk Action Approval Queue</h3>
                  <button className="btn btn-outline" onClick={loadApprovals}>Refresh</button>
                </div>
                {approvals.length === 0 ? (
                  <p style={{ color: 'var(--text-secondary)' }}>No pending approvals.</p>
                ) : (
                  <table>
                    <thead>
                      <tr>
                        <th>Action Type</th>
                        <th>Payload Summary</th>
                        <th>Canonical SHA-256 Hash</th>
                        <th>Status</th>
                        <th>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {approvals.map((appr) => (
                        <tr key={appr.id}>
                          <td><strong>{appr.action_type.toUpperCase()}</strong></td>
                          <td>
                            <pre style={{ fontSize: '0.75rem', background: '#0f172a', padding: 6, borderRadius: 4 }}>
                              {JSON.stringify(appr.proposal_payload, null, 2)}
                            </pre>
                          </td>
                          <td style={{ fontFamily: 'monospace', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                            {appr.proposal_hash.slice(0, 16)}...
                          </td>
                          <td>
                            <span className={`badge ${appr.status === 'PENDING' ? 'badge-yellow' : appr.status === 'APPROVED' ? 'badge-green' : 'badge-red'}`}>
                              {appr.status}
                            </span>
                          </td>
                          <td>
                            {appr.status === 'PENDING' ? (
                              <div style={{ display: 'flex', gap: 6 }}>
                                <button
                                  className="btn btn-success"
                                  onClick={() => handleDecision(appr.id, 'APPROVE')}
                                  disabled={isLoading}
                                >
                                  Approve
                                </button>
                                <button
                                  className="btn btn-danger"
                                  onClick={() => handleDecision(appr.id, 'REJECT')}
                                  disabled={isLoading}
                                >
                                  Reject
                                </button>
                              </div>
                            ) : (
                              <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Resolved</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            )}

            {/* TAB: Human Handoff Queue */}
            {activeTab === 'handoffs' && (
              <div className="card">
                <h3>Human Support Handoff Queue</h3>
                <p style={{ color: 'var(--text-secondary)', marginBottom: 16 }}>
                  Tickets escalated due to budget limits, policy denials, or ambiguity.
                </p>
                {handoffs.length === 0 ? (
                  <p style={{ color: 'var(--text-secondary)' }}>No escalated tickets in queue.</p>
                ) : (
                  <table>
                    <thead>
                      <tr>
                        <th>Ticket ID</th>
                        <th>Reason Code</th>
                        <th>Summary</th>
                        <th>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {handoffs.map((h) => (
                        <tr key={h.id}>
                          <td>{h.ticket_id}</td>
                          <td><span className="badge badge-yellow">{h.reason_code}</span></td>
                          <td>{h.summary}</td>
                          <td><span className="badge badge-blue">{h.status}</span></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            )}

            {/* TAB: Redacted Audit Trail */}
            {activeTab === 'audit' && (
              <div className="card">
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
                  <h3>Audit Trail</h3>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <input
                      type="text"
                      className="chat-input"
                      value={selectedTicketForAudit}
                      onChange={(e) => setSelectedTicketForAudit(e.target.value)}
                      placeholder="Ticket ID"
                      style={{ width: 220 }}
                    />
                    <button className="btn btn-primary" onClick={loadAudit}>Inspect</button>
                  </div>
                </div>
                {auditEvents.length === 0 ? (
                  <p style={{ color: 'var(--text-secondary)' }}>No audit events found for this ticket.</p>
                ) : (
                  <table>
                    <thead>
                      <tr>
                        <th>Timestamp</th>
                        <th>Event Type</th>
                        <th>Actor</th>
                        <th>Resource</th>
                        <th>Redacted Metadata</th>
                      </tr>
                    </thead>
                    <tbody>
                      {auditEvents.map((e) => (
                        <tr key={e.id}>
                          <td style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                            {new Date(e.created_at).toLocaleTimeString()}
                          </td>
                          <td><strong>{e.event_type}</strong></td>
                          <td><span className="badge badge-blue">{e.actor_type}</span></td>
                          <td>{e.resource_type}:{e.resource_id.slice(0, 10)}</td>
                          <td>
                            <pre style={{ fontSize: '0.75rem', background: '#0f172a', padding: 4, borderRadius: 4 }}>
                              {JSON.stringify(e.metadata_redacted)}
                            </pre>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            )}
          </div>
        ) : (
          <div className="auth-page">
            <section className="auth-showcase">
              <div className="auth-kicker">SUPPORT, WITH CLARITY</div>
              <h1>A little more<br /><span>peace of mind.</span></h1>
              <p>Your support, account details, and updates, together in one calm, secure place.</p>
              <div className="auth-feature"><span>01</span><div><strong>Thoughtful help</strong><small>Clear answers, whenever you need them.</small></div></div>
              <div className="auth-feature"><span>02</span><div><strong>Your account stays yours</strong><small>Private sign-in and protected conversations.</small></div></div>
              <div className="auth-orb" />
            </section>
            <section className="auth-card">
              <div className="auth-icon">A</div><div className="auth-kicker">WELCOME TO AGENT V</div>
              <h2>{authMode === 'login' ? 'Sign in' : 'Create your account'}</h2>
              <p className="auth-subtitle">{authMode === 'login' ? 'Enter your details to continue.' : 'A few details and we will get you started.'}</p>
              <form onSubmit={handleAuth} className="auth-form">
                {authMode === 'register' && <label>Full name<input value={authName} onChange={e => setAuthName(e.target.value)} autoComplete="name" minLength={2} maxLength={100} placeholder="Your name" required /></label>}
                <label>Email address<input type="email" value={authEmail} onChange={e => setAuthEmail(e.target.value)} autoComplete="email" placeholder="name@example.com" required /></label>
                <label>Password<input type="password" value={authPassword} onChange={e => setAuthPassword(e.target.value)} autoComplete={authMode === 'login' ? 'current-password' : 'new-password'} minLength={authMode === 'register' ? 12 : 1} maxLength={128} placeholder={authMode === 'register' ? 'At least 12 characters' : 'Your password'} required /></label>
                {authError && <div className="auth-error" role="alert">{authError}</div>}
                <button className="btn btn-primary auth-submit" type="submit" disabled={isLoading}>{isLoading ? 'Please wait...' : authMode === 'login' ? 'Continue' : 'Create account'} <span>-&gt;</span></button>
              </form>
              <div className="auth-switch">{authMode === 'login' ? 'New to Agent V?' : 'Already have an account?'} <button onClick={() => { setAuthMode(authMode === 'login' ? 'register' : 'login'); setAuthError(''); }}>{authMode === 'login' ? 'Create an account' : 'Sign in'}</button></div>
              <div className="auth-terms">By continuing, you agree to our <a href="#">Terms</a> and <a href="#">Privacy Policy</a>.</div>
            </section>
            <footer className="auth-footer">2026 Agent V <span>Secure customer support</span></footer>
          </div>
        )}
      </main>
    </div>
  );
}
