import { useEffect, useRef, useState } from 'react';
import { useApp, useResource } from '../../state/app.tsx';
import { useControlsEnabled } from '../common.tsx';
import { calls } from '../../api/calls.ts';
import type { ChatAnswer } from '../../api/types.ts';

interface OrchestratorChatProps {
  slug: string;
  pid: string;
  onNoteSent?: () => void;
  pendingPrompt?: string | null;
  onClearPendingPrompt?: () => void;
}

export function OrchestratorChat({
  slug,
  pid,
  onNoteSent,
  pendingPrompt,
  onClearPendingPrompt,
}: OrchestratorChatProps) {
  const app = useApp();
  const enabled = useControlsEnabled();
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);
  const [sendingNote, setSendingNote] = useState<string | null>(null);
  const [sentNotes, setSentNotes] = useState<Record<string, boolean>>({});
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const res = useResource<ChatAnswer>(
    ['chat', pid, slug].join('/'),
    (client) => calls.chat(client, slug, pid),
    { project: pid, run: slug, types: ['chat.message'] },
  );
  const resRef = useRef(res);
  resRef.current = res;

  const items = res.data?.items ?? [];
  const hasPending = items.some((m) => m.status === 'pending');

  // Poll every 3 seconds while a reply is pending
  useEffect(() => {
    if (!hasPending) return undefined;
    const timer = setInterval(() => {
      void resRef.current.reload();
    }, 3000);
    return () => clearInterval(timer);
  }, [hasPending]);

  const handleSend = async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || sending || hasPending || !enabled) return;
    setSending(true);
    setErrorMsg(null);
    try {
      await calls.sendChat(app.client, slug, pid, trimmed);
      setDraft('');
      await resRef.current.reload();
    } catch (err: unknown) {
      setErrorMsg((err as { message?: string })?.message || 'Failed to send message');
    } finally {
      setSending(false);
    }
  };

  // Auto-send pending prompt if requested (e.g. from Station tab "Ask" button)
  useEffect(() => {
    if (pendingPrompt && enabled && !hasPending && !sending) {
      const text = pendingPrompt;
      onClearPendingPrompt?.();
      void handleSend(text);
    }
  }, [pendingPrompt, enabled, hasPending, sending]);

  const handleRetry = async (failedOrchId: string) => {
    const idx = items.findIndex((it) => it.id === failedOrchId);
    let userText = '';
    if (idx > 0) {
      for (let i = idx - 1; i >= 0; i--) {
        if (items[i].role === 'user') {
          userText = items[i].text;
          break;
        }
      }
    }
    if (userText) {
      await handleSend(userText);
    }
  };

  const handleSendAsNote = async (msgId: string, text: string) => {
    if (!text.trim() || !enabled || sendingNote) return;
    setSendingNote(msgId);
    try {
      await calls.sendNote(app.client, slug, pid, text);
      setSentNotes((prev) => ({ ...prev, [msgId]: true }));
      onNoteSent?.();
    } catch (err: unknown) {
      setErrorMsg((err as { message?: string })?.message || 'Failed to send note');
    } finally {
      setSendingNote(null);
    }
  };

  const runner = res.data?.orchestrator?.runner || 'claude';
  const model = res.data?.orchestrator?.model;
  const orchLabel = [runner, model].filter(Boolean).join(' · ');

  const suggestions = [
    'Why is this run waiting?',
    'Explain the selected station',
    'What should I check before approving?',
  ];

  return (
    <div className="floor-chat-container">
      {/* Header line */}
      <div className="floor-chat-header">
        Orchestrator · <span className="mono">{orchLabel}</span> · knows run <span className="mono">{slug}</span>, its spec, tasks and logs. It only answers; actions stay with you.
      </div>

      {errorMsg && (
        <div className="banner danger" style={{ margin: '8px 18px 0', fontSize: 12 }}>
          {errorMsg}
        </div>
      )}

      {/* Message list */}
      <ol aria-live="polite" className="floor-chat-list">
        {items.length === 0 ? (
          <li style={{ listStyle: 'none', color: 'var(--floor-text-muted)', fontSize: 13, textAlign: 'center', margin: 'auto' }}>
            No messages yet. Ask a question or pick a suggestion below.
          </li>
        ) : (
          items.map((m) => {
            if (m.role === 'user') {
              return (
                <li key={m.id} className="floor-chat-msg floor-chat-user" data-testid="chat-msg-user">
                  <div className="floor-chat-author" style={{ color: 'var(--floor-working-label)' }}>You</div>
                  <div className="floor-chat-text">{m.text}</div>
                </li>
              );
            }
            return (
              <li key={m.id} className="floor-chat-msg floor-chat-orch" data-testid="chat-msg-orch">
                <div className="floor-chat-author" style={{ color: 'var(--floor-text-muted)' }}>Orchestrator</div>
                {m.status === 'pending' ? (
                  <div className="floor-chat-pending" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span
                      className="floor-pulse"
                      style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--floor-working-ring)', display: 'inline-block' }}
                    />
                    <span>Orchestrator is thinking…</span>
                  </div>
                ) : m.status === 'failed' ? (
                  <div className="floor-chat-failed">
                    <div className="floor-chat-error" style={{ color: 'var(--danger)', marginBottom: 6 }}>
                      {m.error || 'Failed to get reply'}
                    </div>
                    <button
                      type="button"
                      className="floor-chat-retry-btn"
                      disabled={!enabled || hasPending || sending}
                      onClick={() => void handleRetry(m.id)}
                    >
                      Retry
                    </button>
                  </div>
                ) : (
                  <>
                    <div className="floor-chat-text" style={{ marginBottom: 8 }}>{m.text}</div>
                    <button
                      type="button"
                      className="floor-chat-note-btn"
                      disabled={!enabled || sendingNote === m.id}
                      onClick={() => void handleSendAsNote(m.id, m.text)}
                    >
                      {sentNotes[m.id] ? 'Note sent' : 'Send as note to the next agent'}
                    </button>
                  </>
                )}
              </li>
            );
          })
        )}
      </ol>

      {/* Suggestion chips */}
      <div className="floor-chat-chips">
        {suggestions.map((text) => (
          <button
            key={text}
            type="button"
            className="floor-chat-chip"
            disabled={!enabled || hasPending || sending}
            onClick={() => void handleSend(text)}
          >
            {text}
          </button>
        ))}
      </div>

      {/* Form with textarea and Send button */}
      <form
        className="floor-chat-form"
        onSubmit={(e) => {
          e.preventDefault();
          if (draft.trim()) void handleSend(draft);
        }}
      >
        <label htmlFor="orchestrator-chat-input" className="sr-only">
          Message the orchestrator
        </label>
        <textarea
          id="orchestrator-chat-input"
          rows={2}
          placeholder="Ask why a step waits, what a log line means, or what to check before approving"
          value={draft}
          disabled={!enabled || hasPending || sending}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              if (draft.trim() && enabled && !hasPending && !sending) {
                void handleSend(draft);
              }
            }
          }}
        />
        <button
          type="submit"
          className="floor-chat-send-btn"
          disabled={!enabled || hasPending || sending || !draft.trim()}
        >
          Send
        </button>
      </form>
    </div>
  );
}
