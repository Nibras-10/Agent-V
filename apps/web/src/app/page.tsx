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
  workflow_status?: string | null;
  intent?: string | null;
  approval_id?: string | null;
  recommended_action?: { action_type?: string; parameters?: Record<string, unknown>; reason?: string } | null;
}

interface Approval {
  id: string;
  ticket_id: string;
  action_type: string;
  proposal_payload: any;
  proposal_hash: string;
  status: string;
  reviewer_id?: string;
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
  assigned_to?: string | null;
  created_at: string;
  workflow_status?: string | null;
  intent?: string | null;
  approval_id?: string | null;
  recommended_action?: { action_type?: string; parameters?: Record<string, unknown>; reason?: string } | null;
}

interface CustomerOverview {
  customer: { id: string; display_name: string; email: string; phone?: string | null };
  subscriptions: { id: string; plan: string; status: string; started_at: string; cancel_at?: string | null }[];
  transactions: { id: string; amount_minor: number; currency: string; status: string; refundable_minor: number; occurred_at: string }[];
}

interface TicketSummary {
  id: string;
  subject: string;
  status: string;
  priority: string;
  created_at: string;
  updated_at: string;
  customer?: { id: string; display_name: string; email: string; phone?: string | null } | null;
  conversation_count?: number;
  handoff?: { id: string; status: string; assigned_to?: string | null; reason_code: string } | null;
}

interface StaffTicket extends TicketSummary {
  conversations: { id: string; channel: string; messages: Message[] }[];
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
  const [authMode, setAuthMode] = useState<'login' | 'register' | 'forgot' | 'reset'>('login');
  const [authName, setAuthName] = useState('');
  const [authEmail, setAuthEmail] = useState('');
  const [authPassword, setAuthPassword] = useState('');
  const [authError, setAuthError] = useState('');
  const [authSuccess, setAuthSuccess] = useState('');
  const [resetToken, setResetToken] = useState('');
  const [notice, setNotice] = useState('');
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [activeTab, setActiveTab] = useState<'chat' | 'inbox' | 'approvals' | 'handoffs' | 'audit'>('chat');

  // Customer Chat State
  const [conversationId, setConversationId] = useState<string>('');
  const [ticketId, setTicketId] = useState<string>('');
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputMessage, setInputMessage] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [agentStage, setAgentStage] = useState('');
  const [customerOverview, setCustomerOverview] = useState<CustomerOverview | null>(null);
  const [customerTickets, setCustomerTickets] = useState<TicketSummary[]>([]);
  const [demoMode, setDemoMode] = useState(false);
  const [staffTickets, setStaffTickets] = useState<TicketSummary[]>([]);
  const [selectedStaffTicket, setSelectedStaffTicket] = useState<StaffTicket | null>(null);
  const [staffReply, setStaffReply] = useState('');
  const [loadingTab, setLoadingTab] = useState(false);

  // Reviewer State
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [handoffs, setHandoffs] = useState<HandoffItem[]>([]);
  const [auditEvents, setAuditEvents] = useState<AuditItem[]>([]);
  const [decisionComment, setDecisionComment] = useState('');
  const [selectedTicketForAudit, setSelectedTicketForAudit] = useState('');

  const defaultTabForRole = (role: string): 'chat' | 'inbox' | 'approvals' | 'audit' =>
    role === 'customer' ? 'chat' : role === 'support_agent' ? 'inbox' : role === 'auditor' ? 'audit' : 'approvals';

  const apiRequest = async (path: string, init: RequestInit = {}) => {
    const headers = new Headers(init.headers);
    if (token) headers.set('Authorization', `Bearer ${token}`);
    const res = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || 'The request could not be completed. Please try again.');
    return data;
  };

  const loadCustomerOverview = async () => {
    if (!token) return [] as TicketSummary[];
    const [overview, tickets] = await Promise.all([
      apiRequest('/api/v1/customers/me/overview'),
      apiRequest('/api/v1/tickets'),
    ]);
    setCustomerOverview(overview);
    setCustomerTickets(tickets);
    return tickets as TicketSummary[];
  };

  const startCustomerConversation = async () => {
    if (!token) return;
    try {
      const conv = await apiRequest('/api/v1/conversations', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ subject: 'Customer Support Inquiry' }),
      });
      setTicketId(conv.ticket_id);
      setConversationId(conv.id);
      setMessages([]);
      await loadCustomerOverview();
      setNotice('');
    } catch (err: any) {
      setNotice(err.message || 'Could not start a conversation.');
    }
  };

  // Authenticate, register customers, and handle verification/recovery links.
  const handleAuth = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true); setAuthError(''); setAuthSuccess('');
    try {
      const routes = { login: '/token', register: '/register', forgot: '/password/forgot', reset: '/password/reset' } as const;
      const body = authMode === 'register'
        ? { name: authName, email: authEmail, password: authPassword }
        : authMode === 'login' || authMode === 'forgot'
          ? { email: authEmail, password: authPassword }
          : { token: resetToken, new_password: authPassword };
      const res = await fetch(`${API_BASE}/api/v1/auth${routes[authMode]}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || 'Unable to complete this request.');
      if (authMode === 'forgot') { setAuthSuccess(data.detail); return; }
      if (authMode === 'reset') { setAuthSuccess(data.detail); setAuthMode('login'); setAuthPassword(''); return; }
      if (authMode === 'register' && !data.access_token) { setAuthSuccess(data.detail); setAuthMode('login'); setAuthPassword(''); return; }
      const meRes = await fetch(`${API_BASE}/api/v1/auth/me`, { headers: { Authorization: `Bearer ${data.access_token}` } });
      if (!meRes.ok) throw new Error('Your account could not be loaded. Please sign in again.');
      const meData = await meRes.json();
      sessionStorage.setItem('agent-v-token', data.access_token);
      setToken(data.access_token); setCurrentUser(meData);
      setActiveTab(defaultTabForRole(meData.role));
    } catch (err: any) { setAuthError(err.message || 'Something went wrong. Please try again.'); }
    finally { setIsLoading(false); }
  };

  useEffect(() => {
    fetch(`${API_BASE}/health/live`).then(res => res.json()).then(data => setDemoMode(Boolean(data.demo_mode))).catch(() => {});
    const params = new URLSearchParams(window.location.search);
    const verifyToken = params.get('verify_email');
    const passwordToken = params.get('reset_password');
    if (verifyToken) {
      window.history.replaceState({}, '', window.location.pathname);
      fetch(`${API_BASE}/api/v1/auth/verify-email`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token: verifyToken }),
      }).then(async res => { const data = await res.json(); if (!res.ok) throw new Error(data.detail); setAuthSuccess(data.detail); })
        .catch(err => setAuthError(err.message || 'Verification link is invalid or expired.'));
    }
    if (passwordToken) { setResetToken(passwordToken); setAuthMode('reset'); window.history.replaceState({}, '', window.location.pathname); }
    const savedToken = sessionStorage.getItem('agent-v-token');
    if (savedToken) {
      fetch(`${API_BASE}/api/v1/auth/me`, { headers: { Authorization: `Bearer ${savedToken}` } })
        .then(async res => { if (!res.ok) throw new Error('Session expired'); return res.json(); })
        .then(user => { setToken(savedToken); setCurrentUser(user); setActiveTab(defaultTabForRole(user.role)); })
        .catch(() => sessionStorage.removeItem('agent-v-token'));
    }
  }, []);

  const handleLogout = () => { sessionStorage.removeItem('agent-v-token'); setToken(null); setCurrentUser(null); setMessages([]); setCustomerOverview(null); setCustomerTickets([]); setSelectedStaffTicket(null); };

  // Load a selected customer ticket and its conversation history.
  const loadCustomerTicket = async (requestedTicketId?: string) => {
    if (!token) return;
    try {
      setLoadingTab(true);
      let tickets = customerTickets;
      if (!tickets.length || !requestedTicketId) tickets = await loadCustomerOverview();
      const ticket = requestedTicketId
        ? tickets.find(item => item.id === requestedTicketId)
        : tickets[0];
      if (!ticket) {
        setTicketId(''); setConversationId(''); setMessages([]);
        return;
      }
      setTicketId(ticket.id);
      const details = await apiRequest(`/api/v1/tickets/${ticket.id}`);
      let conv = details.conversations?.[0];
      if (!conv) {
        conv = await apiRequest('/api/v1/conversations', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ticket_id: ticket.id, subject: ticket.subject }),
        });
      }
      setConversationId(conv.id); setMessages(conv.messages || []);
      setNotice('');
    } catch (err: any) { setNotice(err.message || 'Unable to load this conversation.'); }
    finally { setLoadingTab(false); }
  };

  // Send message
  const handleSendMessage = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!inputMessage.trim() || !token || !conversationId) return;

    const userText = inputMessage;
    setInputMessage('');
    setIsLoading(true);
    setNotice('');
    setAgentStage('Reviewing your account');
    const progressTimers = [
      window.setTimeout(() => setAgentStage('Checking support guidance'), 1200),
      window.setTimeout(() => setAgentStage('Preparing a response'), 2600),
    ];

    const tempMsg: Message = {
      id: `tmp-${Date.now()}`,
      actor_type: 'customer',
      content: userText,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, tempMsg]);

    try {
      const agentMsg = await apiRequest(`/api/v1/conversations/${conversationId}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: userText }),
      });
      setMessages((prev) => [...prev, agentMsg]);
      if (agentMsg.workflow_status === 'WAITING_FOR_APPROVAL') setNotice('A proposed action is waiting for staff review.');
      if (agentMsg.workflow_status === 'HANDED_OFF') setNotice('Your conversation has been sent to the human support queue.');
      // Sending succeeded; a separate account refresh must not report the message as failed.
      await loadCustomerOverview().catch(() => {});
    } catch (err: any) {
      setMessages((prev) => prev.filter(message => !message.id.startsWith('tmp-')));
      setInputMessage(userText);
      setNotice(err.message || 'Your message could not be sent. Please try again.');
    } finally {
      progressTimers.forEach(window.clearTimeout);
      setAgentStage('');
      setIsLoading(false);
    }
  };

  const loadStaffInbox = async () => {
    if (!token) return;
    setLoadingTab(true);
    try {
      const items = await apiRequest('/api/v1/staff/tickets');
      setStaffTickets(items);
      if (selectedStaffTicket && items.some((item: TicketSummary) => item.id === selectedStaffTicket.id)) {
        await loadStaffTicket(selectedStaffTicket.id);
      }
      setNotice('');
    } catch (err: any) { setNotice(err.message || 'Could not load the staff inbox.'); }
    finally { setLoadingTab(false); }
  };

  const loadStaffTicket = async (id: string) => {
    if (!token) return;
    try {
      const ticket = await apiRequest(`/api/v1/staff/tickets/${id}`);
      setSelectedStaffTicket(ticket);
      setSelectedTicketForAudit(id);
    } catch (err: any) { setNotice(err.message || 'Could not open this ticket.'); }
  };

  const sendStaffReply = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedStaffTicket || !staffReply.trim()) return;
    try {
      await apiRequest(`/api/v1/staff/tickets/${selectedStaffTicket.id}/reply`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: staffReply.trim() }),
      });
      setStaffReply('');
      await loadStaffTicket(selectedStaffTicket.id);
      setNotice('Reply sent to the conversation.');
    } catch (err: any) { setNotice(err.message || 'Could not send the reply.'); }
  };

  const updateStaffTicket = async (patch: { status?: string; priority?: string }) => {
    if (!selectedStaffTicket) return;
    try {
      await apiRequest(`/api/v1/staff/tickets/${selectedStaffTicket.id}`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(patch),
      });
      await loadStaffInbox();
      setNotice('Ticket updated.');
    } catch (err: any) { setNotice(err.message || 'Could not update this ticket.'); }
  };

  const updateHandoff = async (handoffId: string, action: 'assign' | 'resolve') => {
    if (!token) return;
    try {
      await apiRequest(`/api/v1/handoffs/${handoffId}/${action}`, { method: 'POST' });
      await Promise.all([loadHandoffs(), loadStaffInbox()]);
      setNotice(action === 'assign' ? 'Handoff assigned to you.' : 'Handoff resolved.');
    } catch (err: any) { setNotice(err.message || 'Could not update the handoff.'); }
  };

  // Reviewer: Load approvals
  const loadApprovals = async () => {
    if (!token) return;
    try {
      setLoadingTab(true);
      setApprovals(await apiRequest('/api/v1/approvals'));
      setNotice('');
    } catch (err: any) {
      setNotice(err.message || 'Could not load approvals.');
    } finally {
      setLoadingTab(false);
    }
  };

  // Reviewer: Decide approval
  const handleDecision = async (approvalId: string, decision: 'APPROVE' | 'REJECT') => {
    if (!token) return;
    setIsLoading(true);
    try {
      await apiRequest(`/api/v1/approvals/${approvalId}/decision`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decision, comment: decisionComment }),
      });
      setDecisionComment('');
      setNotice(decision === 'APPROVE' ? (demoMode ? 'Approved. The sample action was simulated; no payment provider was contacted.' : 'Approval completed.') : 'Proposal rejected.');
      await loadApprovals();
    } catch (err: any) {
      setNotice(err.message || 'Could not record the decision.');
    } finally {
      setIsLoading(false);
    }
  };

  // Reviewer: Load handoffs
  const loadHandoffs = async () => {
    if (!token) return;
    try {
      setLoadingTab(true);
      setHandoffs(await apiRequest('/api/v1/handoffs'));
      setNotice('');
    } catch (err: any) {
      setNotice(err.message || 'Could not load handoffs.');
    } finally {
      setLoadingTab(false);
    }
  };

  // Auditor: Load audit events
  const loadAudit = async () => {
    if (!token || !selectedTicketForAudit) return;
    try {
      setAuditEvents(await apiRequest(`/api/v1/audit/${selectedTicketForAudit}`));
      setNotice('');
    } catch (err: any) {
      setNotice(err.message || 'Could not load the audit history.');
    }
  };

  useEffect(() => {
    if (token) {
      if (activeTab === 'chat') loadCustomerTicket();
      if (activeTab === 'approvals') loadApprovals();
      if (activeTab === 'handoffs') loadHandoffs();
      if (activeTab === 'audit') loadAudit();
      if (activeTab === 'inbox') { loadStaffInbox(); loadHandoffs(); }
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
                <button className={`tab ${activeTab === 'chat' ? 'active' : ''}`} onClick={() => setActiveTab('chat')}>My support</button>
              )}
              {['support_agent', 'reviewer', 'admin', 'auditor'].includes(currentUser.role) && (
                <button className={`tab ${activeTab === 'inbox' ? 'active' : ''}`} onClick={() => setActiveTab('inbox')}>Ticket inbox</button>
              )}
              {['reviewer', 'admin', 'auditor'].includes(currentUser.role) && (
                <button className={`tab ${activeTab === 'approvals' ? 'active' : ''}`} onClick={() => setActiveTab('approvals')}>
                  Approvals <span className="tab-count">{approvals.filter(a => a.status === 'PENDING').length}</span>
                </button>
              )}
              {['support_agent', 'reviewer', 'admin'].includes(currentUser.role) && (
                <button className={`tab ${activeTab === 'handoffs' ? 'active' : ''}`} onClick={() => setActiveTab('handoffs')}>
                  Human handoffs <span className="tab-count">{handoffs.filter(h => h.status !== 'RESOLVED').length}</span>
                </button>
              )}
              {['reviewer', 'admin', 'auditor'].includes(currentUser.role) && (
                <button className={`tab ${activeTab === 'audit' ? 'active' : ''}`} onClick={() => setActiveTab('audit')}>Activity</button>
              )}
            </div>

            {/* TAB: Customer Chat */}
            {activeTab === 'chat' && (
              <div className="customer-workspace">
                <aside className="workspace-panel ticket-list-panel">
                  <div className="panel-heading"><div><span className="eyebrow">YOUR SUPPORT</span><h2>Conversations</h2></div>
                    <button className="icon-button" title="Start a new conversation" onClick={startCustomerConversation}>＋</button></div>
                  <button className="new-conversation-button" onClick={startCustomerConversation}>＋ New conversation</button>
                  <div className="ticket-list">
                    {customerTickets.map(ticket => (
                      <button key={ticket.id} className={`ticket-list-item ${ticketId === ticket.id ? 'selected' : ''}`} onClick={() => loadCustomerTicket(ticket.id)}>
                        <span className="ticket-list-title">{ticket.subject}</span>
                        <span className="ticket-list-meta">{new Date(ticket.updated_at).toLocaleDateString()} <span className={`status-dot status-${ticket.status.toLowerCase()}`} /> {ticket.status.replaceAll('_', ' ')}</span>
                      </button>
                    ))}
                    {!loadingTab && customerTickets.length === 0 && <p className="quiet-empty">Your conversations will appear here.</p>}
                  </div>
                  {demoMode && <div className="demo-side-note">Demo account · sample information</div>}
                </aside>

                <section className="workspace-panel conversation-panel">
                  <div className="conversation-heading">
                    <div><span className="eyebrow">CUSTOMER SUPPORT</span><h2>{customerTickets.find(t => t.id === ticketId)?.subject || 'How can we help?'}</h2></div>
                    {ticketId && <div className="conversation-heading-actions"><span className="status-pill">{customerTickets.find(t => t.id === ticketId)?.status?.replaceAll('_', ' ') || 'Open'}</span><button className="text-button" onClick={() => loadCustomerTicket(ticketId)}>Refresh</button></div>}
                  </div>
                  <div className="suggestion-list" aria-label="Suggested requests">
                    <button className="suggestion-chip" onClick={() => setInputMessage('What is my subscription plan status?')}>Check my plan</button>
                    <button className="suggestion-chip" onClick={() => setInputMessage('I have a question about a recent charge.')}>Ask about a charge</button>
                    <button className="suggestion-chip" onClick={() => setInputMessage('I think there is a duplicate charge. Please review whether my refundable demo charge qualifies for a refund.')}>Review a demo refund</button>
                    <button className="suggestion-chip" onClick={() => setInputMessage('I need help with my subscription.')}>Subscription help</button>
                    <button className="suggestion-chip" onClick={() => setInputMessage('Please cancel my demo subscription at the end of its current period.')}>Cancel a demo plan</button>
                    <button className="suggestion-chip" onClick={() => setInputMessage('I need to update my contact information.')}>Update contact details</button>
                    <button className="suggestion-chip" onClick={() => setInputMessage('I would like to speak with a support specialist.')}>Talk to a person</button>
                  </div>
                  <div className="chat-box">
                    <div className="chat-messages">
                      {loadingTab && messages.length === 0 && <div className="inline-loading">Loading your support history…</div>}
                      {messages.length === 0 && !loadingTab && <div className="chat-empty"><div className="empty-icon">A</div><h3>We’re here to help</h3><p>Ask about your plan, a charge, or anything else you need.</p><button className="btn btn-outline" onClick={() => setInputMessage('I need help with my account.')}>Ask a question</button></div>}
                      {messages.map((m) => (
                        <div key={m.id} className={`message-row ${m.actor_type === 'customer' ? 'message-row-customer' : ''}`}>
                          <div className={`message-bubble ${m.actor_type === 'customer' ? 'msg-customer' : 'msg-agent'}`}>
                            <div className="message-author">{m.actor_type === 'customer' ? 'You' : m.actor_type === 'agent' ? 'Support assistant' : m.actor_type === 'support_agent' ? 'Support team' : m.actor_type}</div>
                            <div>{m.content}</div>
                            {m.actor_type === 'agent' && m.workflow_status && <div className="agent-outcome">
                              {m.intent && <span className="outcome-intent">Request type · {m.intent.replaceAll('_', ' ')}</span>}
                              {m.recommended_action && <div><strong>Recommendation · {m.recommended_action.action_type?.replaceAll('_', ' ') || 'support action'}</strong>{m.recommended_action.reason && <small>{m.recommended_action.reason}</small>}</div>}
                              {m.workflow_status === 'WAITING_FOR_APPROVAL' && <span className="mini-status pending_approval">Waiting for human approval</span>}
                              {m.workflow_status === 'HANDED_OFF' && <span className="mini-status assigned">Sent to human support</span>}
                              {m.recommended_action && demoMode && <small>Demo simulation · no payment provider was contacted</small>}
                            </div>}
                            <time>{new Date(m.created_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}</time>
                          </div>
                        </div>
                      ))}
                      {isLoading && <div className="message-row"><div className="message-bubble msg-agent agent-activity"><span className="pulse-dot" />{agentStage || 'Working on your request…'}</div></div>}
                    </div>
                    <form className="chat-input-bar" onSubmit={handleSendMessage}>
                      <input type="text" className="chat-input" placeholder="Write a message…" value={inputMessage} onChange={(e) => setInputMessage(e.target.value)} disabled={isLoading || !conversationId} />
                      <button type="submit" className="btn btn-primary" disabled={isLoading || !inputMessage.trim() || !conversationId}>Send</button>
                    </form>
                  </div>
                  {demoMode && <p className="demo-disclaimer">Demo mode · any approved payment action changes sample data only. No payment is sent.</p>}
                </section>

                <aside className="workspace-panel account-panel">
                  <div className="panel-heading"><div><span className="eyebrow">ACCOUNT DETAILS</span><h2>Your account</h2></div><button className="text-button" onClick={() => loadCustomerOverview().catch((err: any) => setNotice(err.message))}>Refresh</button></div>
                  {customerOverview ? <>
                    <div className="profile-card"><div className="profile-avatar">{customerOverview.customer.display_name.slice(0, 1).toUpperCase()}</div><div><strong>{customerOverview.customer.display_name}</strong><small>{customerOverview.customer.email}</small></div></div>
                    <div className="context-section"><div className="section-label">SUBSCRIPTIONS</div>
                      {customerOverview.subscriptions.map(sub => <div className="context-row" key={sub.id}><div><strong>{sub.plan}</strong><small>Started {new Date(sub.started_at).toLocaleDateString()}</small></div><span className={`mini-status ${sub.status}`}>{sub.status}</span></div>)}
                      {!customerOverview.subscriptions.length && <p className="quiet-empty">No subscriptions on file.</p>}
                    </div>
                    <div className="context-section"><div className="section-label">RECENT CHARGES</div>
                      {customerOverview.transactions.map(txn => <div className="context-row" key={txn.id}><div><strong>{new Intl.NumberFormat(undefined, { style: 'currency', currency: txn.currency }).format(txn.amount_minor / 100)}</strong><small>{new Date(txn.occurred_at).toLocaleDateString()} · {txn.refundable_minor > 0 ? `${new Intl.NumberFormat(undefined, { style: 'currency', currency: txn.currency }).format(txn.refundable_minor / 100)} eligible` : 'No refund available'}</small></div><span className={`mini-status ${txn.status}`}>{txn.status}</span></div>)}
                      {!customerOverview.transactions.length && <p className="quiet-empty">No recent charges.</p>}
                    </div>
                  </> : <p className="quiet-empty">Account details will appear here when loaded.</p>}
                </aside>
              </div>
            )}

            {activeTab === 'inbox' && (
              <div className="staff-workspace">
                <section className="workspace-panel inbox-list-panel">
                  <div className="panel-heading"><div><span className="eyebrow">SUPPORT TEAM</span><h2>Ticket inbox</h2></div><button className="text-button" onClick={loadStaffInbox}>Refresh</button></div>
                  {loadingTab && <p className="quiet-empty">Loading tickets…</p>}
                  <div className="staff-ticket-list">{staffTickets.map(ticket => <button key={ticket.id} className={`staff-ticket-item ${selectedStaffTicket?.id === ticket.id ? 'selected' : ''}`} onClick={() => loadStaffTicket(ticket.id)}>
                    <div className="ticket-item-top"><strong>{ticket.subject}</strong><span className={`mini-status ${ticket.status}`}>{ticket.status.replaceAll('_', ' ')}</span></div>
                    <span className="ticket-list-meta">{ticket.customer?.display_name || 'Customer'} · {ticket.priority} priority</span>
                    {ticket.handoff && <span className="handoff-indicator">Human handoff · {ticket.handoff.status.toLowerCase()}</span>}
                  </button>)}</div>
                  {!loadingTab && staffTickets.length === 0 && <p className="quiet-empty">No support tickets yet.</p>}
                </section>
                <section className="workspace-panel staff-ticket-detail">
                  {selectedStaffTicket ? <>
                    <div className="conversation-heading"><div><span className="eyebrow">{selectedStaffTicket.id}</span><h2>{selectedStaffTicket.subject}</h2></div><span className={`mini-status ${selectedStaffTicket.status}`}>{selectedStaffTicket.status.replaceAll('_', ' ')}</span></div>
                    {['support_agent', 'reviewer', 'admin'].includes(currentUser.role) && <div className="staff-meta-controls">
                      <label>Status<select value={selectedStaffTicket.status} onChange={e => updateStaffTicket({ status: e.target.value })}><option value="open">Open</option><option value="in_progress">In progress</option><option value="pending_approval">Pending approval</option><option value="handed_off">Handed off</option><option value="resolved">Resolved</option></select></label>
                      <label>Priority<select value={selectedStaffTicket.priority} onChange={e => updateStaffTicket({ priority: e.target.value })}><option value="low">Low</option><option value="normal">Normal</option><option value="high">High</option><option value="urgent">Urgent</option></select></label>
                    </div>}
                    {selectedStaffTicket.customer && <div className="staff-customer-card"><strong>{selectedStaffTicket.customer.display_name}</strong><span>{selectedStaffTicket.customer.email}</span>{selectedStaffTicket.customer.phone && <span>{selectedStaffTicket.customer.phone}</span>}</div>}
                    <div className="staff-messages">{selectedStaffTicket.conversations.flatMap(conv => conv.messages).map(message => <div className={`staff-message ${message.actor_type === 'customer' ? 'from-customer' : ''}`} key={message.id}><span>{message.actor_type === 'customer' ? 'Customer' : message.actor_type === 'support_agent' ? 'Support agent' : 'Support assistant'} · {new Date(message.created_at).toLocaleString()}</span><p>{message.content}</p></div>)}</div>
                    {['support_agent', 'reviewer', 'admin'].includes(currentUser.role) && <form className="staff-reply-form" onSubmit={sendStaffReply}>
                      <textarea value={staffReply} onChange={e => setStaffReply(e.target.value)} placeholder="Write a reply to the customer…" maxLength={4000} rows={3} />
                      <button className="btn btn-primary" disabled={!staffReply.trim()}>Send reply</button>
                    </form>}
                    {selectedStaffTicket.handoff ? <div className="staff-actions"><span className="demo-disclaimer">{selectedStaffTicket.handoff.assigned_to === currentUser.id ? 'Assigned to you' : selectedStaffTicket.handoff.assigned_to ? 'Assigned to another teammate' : 'Waiting for an owner'}</span>
                      {selectedStaffTicket.handoff.assigned_to !== currentUser.id && <button className="btn btn-outline" onClick={() => updateHandoff(selectedStaffTicket.handoff!.id, 'assign')}>Assign to me</button>}
                      <button className="btn btn-primary" onClick={() => updateHandoff(selectedStaffTicket.handoff!.id, 'resolve')}>Resolve handoff</button>
                    </div> : <p className="quiet-empty">This ticket has no active human handoff.</p>}
                    {demoMode && <div className="demo-disclaimer">Sample customer record · actions are simulated.</div>}
                  </> : <div className="staff-empty"><div className="empty-icon">✳</div><h3>Select a ticket</h3><p>Open a conversation from the inbox to review its context and history.</p></div>}
                </section>
              </div>
            )}

            {/* TAB: Reviewer Approval Queue */}
            {activeTab === 'approvals' && (
              <div className="card">
                <div className="panel-heading"><div><span className="eyebrow">HUMAN REVIEW</span><h2>Action approvals</h2></div>
                  <button className="btn btn-outline" onClick={loadApprovals}>Refresh</button>
                </div>
                {demoMode && <div className="demo-banner"><strong>Safe demo actions</strong><span>Approving updates sample records only. No payment provider is contacted.</span></div>}
                <label className="decision-comment">Reviewer note <textarea value={decisionComment} onChange={e => setDecisionComment(e.target.value)} placeholder="Optional note for the audit history" rows={2} /></label>
                {approvals.length === 0 ? (
                  <div className="staff-empty"><div className="empty-icon">✓</div><h3>All caught up</h3><p>No action proposals are waiting for review.</p></div>
                ) : (
                  <div className="approval-list">
                    {approvals.map((appr) => <article className="approval-card" key={appr.id}>
                      <div className="approval-card-top"><div><span className="eyebrow">{appr.action_type.replaceAll('_', ' ')} · ticket {appr.ticket_id.slice(0, 10)}</span><h3>{appr.action_type === 'refund' ? `Refund ${(Number(appr.proposal_payload.amount_minor || 0) / 100).toFixed(2)} ${appr.proposal_payload.currency || 'USD'}` : appr.action_type === 'cancellation' ? 'Subscription cancellation' : 'Contact update'}</h3></div>
                        <span className={`mini-status ${appr.status}`}>{appr.status.toLowerCase()}</span></div>
                      <p className="approval-reason">{appr.proposal_payload.reason || 'Review the customer request and supporting account data.'}</p>
                      <details className="review-details"><summary>View proposal details</summary><pre>{JSON.stringify(appr.proposal_payload, null, 2)}</pre><small>Integrity hash: {appr.proposal_hash.slice(0, 24)}…</small></details>
                      {appr.status === 'PENDING' && <div className="approval-actions">
                        <button className="btn btn-success" onClick={() => handleDecision(appr.id, 'APPROVE')} disabled={isLoading}>{demoMode ? 'Approve & simulate' : 'Approve action'}</button>
                        <button className="btn btn-outline" onClick={() => handleDecision(appr.id, 'REJECT')} disabled={isLoading}>Reject proposal</button>
                      </div>}
                    </article>)}
                  </div>
                )}
              </div>
            )}

            {/* TAB: Human Handoff Queue */}
            {activeTab === 'handoffs' && (
              <div className="card">
                <div className="panel-heading"><div><span className="eyebrow">TEAM WORKLOAD</span><h2>Human handoffs</h2></div><button className="btn btn-outline" onClick={loadHandoffs}>Refresh</button></div>
                <p className="section-intro">Customers asking for a person, or conversations the assistant needs help with.</p>
                {handoffs.length === 0 ? (
                  <div className="staff-empty"><div className="empty-icon">✓</div><h3>No open handoffs</h3><p>New escalations will appear here.</p></div>
                ) : (
                  <div className="handoff-list">{handoffs.map(h => <article className="handoff-card" key={h.id}>
                    <div><span className="eyebrow">TICKET {h.ticket_id.slice(0, 12)}</span><h3>{h.summary}</h3><p>{h.reason_code.replaceAll('_', ' ')} · {new Date(h.created_at).toLocaleString()}</p></div>
                    <div className="handoff-card-actions"><span className={`mini-status ${h.status}`}>{h.status.toLowerCase()}</span>
                      {h.assigned_to !== currentUser.id && <button className="btn btn-outline" onClick={() => updateHandoff(h.id, 'assign')}>Assign to me</button>}
                      <button className="btn btn-primary" onClick={() => { setActiveTab('inbox'); loadStaffTicket(h.ticket_id); }}>Open ticket</button>
                    </div>
                  </article>)}</div>
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
              <h2>{authMode === 'login' ? 'Sign in' : authMode === 'register' ? 'Create your account' : authMode === 'forgot' ? 'Reset your password' : 'Choose a new password'}</h2>
              <p className="auth-subtitle">{authMode === 'login' ? 'Enter your details to continue.' : authMode === 'register' ? 'A few details and we will get you started.' : authMode === 'forgot' ? 'We will email a secure reset link if your account exists.' : 'Choose a password with at least 12 characters.'}</p>
              <form onSubmit={handleAuth} className="auth-form">
                {authMode === 'register' && <label>Full name<input value={authName} onChange={e => setAuthName(e.target.value)} autoComplete="name" minLength={2} maxLength={100} placeholder="Your name" required /></label>}
                {(authMode === 'login' || authMode === 'register' || authMode === 'forgot') && <label>Email address<input type="email" value={authEmail} onChange={e => setAuthEmail(e.target.value)} autoComplete="email" placeholder="name@example.com" required /></label>}
                {authMode !== 'forgot' && <label>Password<input type="password" value={authPassword} onChange={e => setAuthPassword(e.target.value)} autoComplete={authMode === 'login' ? 'current-password' : 'new-password'} minLength={authMode === 'register' || authMode === 'reset' ? 12 : 1} maxLength={128} placeholder={authMode === 'register' || authMode === 'reset' ? 'At least 12 characters' : 'Your password'} required /></label>}
                {authError && <div className="auth-error" role="alert">{authError}</div>}
                {authSuccess && <div className="auth-success" role="status">{authSuccess}</div>}
                <button className="btn btn-primary auth-submit" type="submit" disabled={isLoading}>{isLoading ? 'Please wait...' : authMode === 'login' ? 'Continue' : authMode === 'register' ? 'Create account' : authMode === 'forgot' ? 'Send reset link' : 'Save new password'} <span>-&gt;</span></button>
              </form>
              {authMode === 'login' && <div className="auth-forgot"><button onClick={() => { setAuthMode('forgot'); setAuthError(''); setAuthSuccess(''); }}>Forgot password?</button></div>}
              <div className="auth-switch">{authMode === 'login' || authMode === 'forgot' ? 'New to Agent V?' : 'Already have an account?'} <button onClick={() => { setAuthMode(authMode === 'register' ? 'login' : authMode === 'forgot' || authMode === 'reset' ? 'login' : 'register'); setAuthError(''); setAuthSuccess(''); }}>{authMode === 'register' || authMode === 'forgot' || authMode === 'reset' ? 'Sign in' : 'Create an account'}</button></div>
              {authError.includes('Verify your email') && <div className="auth-forgot"><button onClick={async () => { if (!authEmail) return; const r = await fetch(`${API_BASE}/api/v1/auth/verification/resend`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email: authEmail }) }); const d = await r.json(); setAuthError(''); setAuthSuccess(d.detail); }}>Resend verification email</button></div>}
              <div className="auth-terms">By continuing, you agree to our <a href="#">Terms</a> and <a href="#">Privacy Policy</a>.</div>
            </section>
            <footer className="auth-footer">2026 Agent V <span>Secure customer support</span></footer>
          </div>
        )}
      </main>
    </div>
  );
}
