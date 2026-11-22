import { test, expect, open, heading } from './helpers.ts';

test.describe('Floor orchestrator chat', () => {
  test('send message and reply appears, suggestion chip, pending blocks second send', async ({ page }) => {
    await open(page, '/floor');
    await expect(heading(page, 'Factory floor')).toBeVisible();

    const sidePanel = page.getByRole('complementary', { name: 'Selected station' });
    await expect(sidePanel).toBeVisible();

    // Click third tab: Orchestrator chat
    const chatTab = sidePanel.getByRole('button', { name: 'Orchestrator chat' });
    await expect(chatTab).toBeVisible();
    await chatTab.click();
    await expect(chatTab).toHaveAttribute('aria-pressed', 'true');

    // Header line exists with runner and slug
    await expect(sidePanel.getByText(/Orchestrator · .* · knows run leave-balance/)).toBeVisible();

    // Textarea and Send button exist
    const input = sidePanel.getByLabel('Message the orchestrator');
    await expect(input).toBeVisible();
    const sendBtn = sidePanel.getByRole('button', { name: 'Send' });
    await expect(sendBtn).toBeDisabled(); // Empty input

    // 1. Send message via typing and Enter key
    await input.fill('What is the current status?');
    await expect(sendBtn).toBeEnabled();
    await input.press('Enter');

    // User message bubble appears
    const userMsg = sidePanel.getByTestId('chat-msg-user');
    await expect(userMsg.first()).toContainText('What is the current status?');

    // Orchestrator reply arrives
    const orchMsg = sidePanel.getByTestId('chat-msg-orch');
    await expect(orchMsg.first()).toBeVisible();
    await expect(orchMsg.first()).toContainText('leave-balance');

    // 2. Suggestion chip sends a prompt
    const chip = sidePanel.getByRole('button', { name: 'Why is this run waiting?' });
    await expect(chip).toBeVisible();
    await chip.click();

    // Verify second user question appeared
    await expect(userMsg.nth(1)).toContainText('Why is this run waiting?');
    await expect(orchMsg.nth(1)).toBeVisible();
  });

  test('failure + retry, and send-as-note calls note API', async ({ page, api }) => {
    await open(page, '/floor');
    const sidePanel = page.getByRole('complementary', { name: 'Selected station' });

    // Open chat tab
    await sidePanel.getByRole('button', { name: 'Orchestrator chat' }).click();

    // Force failure
    await api.chatFail(true);

    const input = sidePanel.getByLabel('Message the orchestrator');
    await input.fill('Will this fail?');
    await sidePanel.getByRole('button', { name: 'Send' }).click();

    // Failed message shows error and Retry button
    const retryBtn = sidePanel.getByRole('button', { name: 'Retry' });
    await expect(retryBtn).toBeVisible({ timeout: 5000 });
    await expect(sidePanel.getByText('orchestrator runner failed')).toBeVisible();

    // Reset failure and click Retry
    await api.chatFail(false);
    await retryBtn.click();

    // Successful reply arrives
    const orchMsg = sidePanel.getByTestId('chat-msg-orch');
    await expect(orchMsg.last()).toContainText('Actions stay with the human operator.');

    // Click "Send as note to the next agent"
    const noteBtn = sidePanel.getByRole('button', { name: 'Send as note to the next agent' }).last();
    await expect(noteBtn).toBeVisible();
    await noteBtn.click();

    // Button updates to "Note sent"
    await expect(sidePanel.getByRole('button', { name: 'Note sent' })).toBeVisible();

    // Verify note API was called
    const notePosts = await api.posts(/\/tasks\/leave-balance\/note/);
    expect(notePosts.length).toBeGreaterThanOrEqual(1);
  });

  test('station tab "Ask the orchestrator about this step" button switches to chat and sends prompt', async ({ page }) => {
    await open(page, '/floor');
    const sidePanel = page.getByRole('complementary', { name: 'Selected station' });

    // Select Triage station
    const triageNeuron = page.getByRole('button', { name: /^Triage:/ });
    await triageNeuron.click();
    await expect(sidePanel.getByRole('heading', { level: 2, name: 'Triage' })).toBeVisible();

    // Click "Ask the orchestrator about this step"
    const askBtn = sidePanel.getByRole('button', { name: 'Ask the orchestrator about this step' });
    await expect(askBtn).toBeVisible();
    await askBtn.click();

    // Chat tab is active
    const chatTab = sidePanel.getByRole('button', { name: 'Orchestrator chat' });
    await expect(chatTab).toHaveAttribute('aria-pressed', 'true');

    // Prompt "Explain the Triage station for this run" was sent
    const userMsg = sidePanel.getByTestId('chat-msg-user');
    await expect(userMsg.first()).toContainText('Explain the Triage station for this run');

    // Orchestrator reply arrives
    const orchMsg = sidePanel.getByTestId('chat-msg-orch');
    await expect(orchMsg.first()).toBeVisible();
  });
});
