import { describe, expect, it } from 'vitest';
import { mergeChatItems, chat as adaptChat } from '../../src/api/adapt.ts';
import type { ChatItem } from '../../src/api/types.ts';
import type { WChatAnswer } from '../../src/api/wire.ts';

describe('chat adapter and merge logic', () => {
  it('mergeChatItems keeps the last line per id while preserving insertion order', () => {
    const raw: ChatItem[] = [
      { id: 'u1', role: 'user', text: 'hello', at: '2026-11-22T10:00:00Z', status: 'done' },
      { id: 'o1', role: 'orchestrator', text: '', at: '2026-11-22T10:00:01Z', status: 'pending' },
      { id: 'u2', role: 'user', text: 'second', at: '2026-11-22T10:01:00Z', status: 'done' },
      { id: 'o1', role: 'orchestrator', text: 'replied', at: '2026-11-22T10:01:05Z', status: 'done' },
    ];

    const merged = mergeChatItems(raw);
    expect(merged).toHaveLength(3);
    expect(merged[0].id).toBe('u1');
    expect(merged[1].id).toBe('o1');
    expect(merged[1].status).toBe('done');
    expect(merged[1].text).toBe('replied');
    expect(merged[2].id).toBe('u2');
  });

  it('adaptChat handles default orchestrator runner and null model', () => {
    const wire: WChatAnswer = {
      items: [
        { id: 'u1', role: 'user', text: 'hello', at: '2026-11-22T10:00:00Z', status: 'done' },
      ],
      orchestrator: {
        runner: 'claude',
        model: null,
      },
    };

    const adapted = adaptChat(wire);
    expect(adapted.items).toHaveLength(1);
    expect(adapted.orchestrator.runner).toBe('claude');
    expect(adapted.orchestrator.model).toBeNull();
  });
});
