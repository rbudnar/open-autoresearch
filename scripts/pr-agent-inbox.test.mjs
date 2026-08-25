import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import {
  analyzeInbox,
  defaultAttentionLabel,
  ensureLabel,
  fetchBranchProtection,
  fetchReviewThreads,
  parseArgs,
  publishInboxSideEffects,
  publishStatus,
  renderMarkdown,
  shouldExitNonzero,
  syncAttentionLabel,
  updateStickyComment,
} from './pr-agent-inbox.mjs';

test('resolved review thread is clean', () => {
  const result = analyzeInbox(data({
    reviewThreads: [
      thread({ isResolved: true, body: 'resolved already' }),
    ],
  }));

  assert.equal(result.clean, true);
  assert.equal(result.agentAttention, false);
  assert.equal(result.statusState, 'success');
});

test('unresolved outdated review thread still blocks until resolved', () => {
  const result = analyzeInbox(data({
    reviewThreads: [
      thread({ isOutdated: true, body: 'please normalize this' }),
    ],
  }));

  assert.equal(result.clean, false);
  assert.equal(result.agentAttention, true);
  assert.equal(result.statusState, 'failure');
  assert.equal(result.items[0].kind, 'review_thread');
});

test('fetchReviewThreads unwraps gh GraphQL data responses', () => {
  const rows = fetchReviewThreads(fakeClient({
    responses: {
      graphql: {
        data: {
          repository: {
            pullRequest: {
              reviewThreads: {
                pageInfo: { hasNextPage: false, endCursor: null },
                nodes: [thread({ body: 'live thread' })],
              },
            },
          },
        },
      },
    },
  }), { owner: 'owner', name: 'repo', pr: 1 });

  assert.equal(rows.length, 1);
  assert.equal(rows[0].comments.nodes[0].body, 'live thread');
});

test('body-only requested changes block without inline threads', () => {
  const result = analyzeInbox(data({
    prView: {
      reviewDecision: 'CHANGES_REQUESTED',
      latestReviews: [
        { id: 'review-1', state: 'CHANGES_REQUESTED', body: 'Please fix the release note.', author: { login: 'reviewer' }, url: 'https://example/review' },
      ],
    },
    reviews: [
      { id: 1, state: 'CHANGES_REQUESTED', body: 'Please fix the release note.', user: { login: 'reviewer' }, html_url: 'https://example/review' },
    ],
  }));

  assert.equal(result.clean, false);
  assert.equal(result.agentAttention, true);
  assert.equal(result.items[0].kind, 'review_decision');
  assert.match(result.items[0].summary, /release note/);
});

test('requested-changes summary prefers active latest review over stale REST history', () => {
  const result = analyzeInbox(data({
    prView: {
      reviewDecision: 'CHANGES_REQUESTED',
      latestReviews: [
        { id: 'active-review', state: 'CHANGES_REQUESTED', body: 'Active blocker.', author: { login: 'reviewer-a' }, url: 'https://example/active' },
      ],
    },
    reviews: [
      { id: 1, state: 'CHANGES_REQUESTED', body: 'Stale blocker.', user: { login: 'reviewer-b' }, html_url: 'https://example/stale' },
      { id: 2, state: 'APPROVED', body: 'Approved now.', user: { login: 'reviewer-b' }, html_url: 'https://example/approve' },
    ],
  }));

  assert.match(result.items[0].summary, /Active blocker/);
  assert.equal(result.items[0].url, 'https://example/active');
});


test('review required is waiting, not agent attention, and not clean', () => {
  const result = analyzeInbox(data({
    prView: {
      reviewDecision: 'REVIEW_REQUIRED',
    },
  }));

  assert.equal(result.clean, false);
  assert.equal(result.agentAttention, false);
  assert.equal(result.inboxState, 'waiting');
  assert.equal(result.statusState, 'success');
  assert.equal(result.statusDescription, 'No agent-actionable inbox items');
  assert.equal(result.items[0].kind, 'review_required');
});

test('dirty merge state is agent-actionable', () => {
  const result = analyzeInbox(data({
    prView: {
      mergeStateStatus: 'DIRTY',
    },
  }));

  assert.equal(result.clean, false);
  assert.equal(result.agentAttention, true);
  assert.equal(result.items[0].kind, 'merge_state');
});

test('same-repo behind branch is agent-actionable merge-readiness work', () => {
  const result = analyzeInbox(data({
    prView: {
      mergeStateStatus: 'BEHIND',
      isCrossRepository: false,
    },
  }));

  assert.equal(result.clean, false);
  assert.equal(result.agentAttention, true);
  assert.equal(result.statusState, 'failure');
  assert.equal(result.items[0].id, 'merge-behind');
});

test('unknown merge state is waiting and not clean', () => {
  const result = analyzeInbox(data({
    prView: {
      mergeStateStatus: 'UNKNOWN',
    },
  }));

  assert.equal(result.clean, false);
  assert.equal(result.agentAttention, false);
  assert.equal(result.inboxState, 'waiting');
  assert.equal(result.statusState, 'success');
});

test('waiting markdown distinguishes inbox state from agent check state', () => {
  const markdown = renderMarkdown(analyzeInbox(data({
    prView: {
      reviewDecision: 'REVIEW_REQUIRED',
    },
  })));

  assert.match(markdown, /Status: Waiting/);
  assert.match(markdown, /Inbox state: waiting/);
  assert.match(markdown, /Agent check state: success/);
  assert.match(markdown, /Agent attention: no/);
});

test('unstable merge state does not block when only optional checks are failing', () => {
  const result = analyzeInbox(data({
    prView: {
      mergeStateStatus: 'UNSTABLE',
      statusCheckRollup: [
        { name: 'Optional experiment', conclusion: 'FAILURE' },
      ],
    },
    branchProtection: {
      required_status_checks: { contexts: [] },
    },
  }));

  assert.equal(result.clean, true);
  assert.equal(result.agentAttention, false);
});

test('blocked merge state does not self-deadlock on ignored inbox status', () => {
  const result = analyzeInbox(data({
    prView: {
      mergeStateStatus: 'BLOCKED',
      statusCheckRollup: [
        { name: 'agent-inbox-clean', state: 'PENDING' },
      ],
    },
    branchProtection: {
      required_status_checks: { contexts: ['agent-inbox-clean'] },
    },
  }), {
    ignoreChecks: ['agent-inbox-clean'],
    allowPendingChecks: true,
  });

  assert.equal(result.clean, true);
  assert.equal(result.statusState, 'success');
});

test('has-hooks merge state is mergeable and does not block by itself', () => {
  const result = analyzeInbox(data({
    prView: {
      mergeStateStatus: 'HAS_HOOKS',
      statusCheckRollup: [],
    },
  }));

  assert.equal(result.clean, true);
  assert.equal(result.agentAttention, false);
  assert.equal(result.statusState, 'success');
});

test('failed required check blocks and inbox check is ignored', () => {
  const result = analyzeInbox(data({
    prView: {
      statusCheckRollup: [
        { name: 'Template Fitness', conclusion: 'FAILURE', detailsUrl: 'https://example/check' },
        { name: 'agent-inbox-clean', conclusion: 'FAILURE' },
      ],
    },
    branchProtection: {
      required_status_checks: {
        contexts: ['Template Fitness', 'agent-inbox-clean'],
      },
    },
  }));

  assert.equal(result.clean, false);
  assert.equal(result.agentAttention, true);
  assert.deepEqual(result.checks.failed, ['Template Fitness']);
});

test('required workflow slash job contexts match split check rollup names', () => {
  const result = analyzeInbox(data({
    prView: {
      statusCheckRollup: [
        { workflowName: 'Template Fitness', name: 'template-fitness', conclusion: 'FAILURE' },
      ],
    },
    branchProtection: {
      required_status_checks: {
        contexts: ['Template Fitness / template-fitness'],
      },
    },
  }));

  assert.equal(result.clean, false);
  assert.equal(result.agentAttention, true);
  assert.deepEqual(result.checks.failed, ['template-fitness']);
});

test('fallback required-check scan treats non-inbox failures as required', () => {
  const result = analyzeInbox(data({
    prView: {
      statusCheckRollup: [
        { name: 'Template Fitness', conclusion: 'FAILURE' },
        { workflowName: 'PR Agent Inbox', name: 'Agent inbox', conclusion: 'FAILURE' },
      ],
    },
    branchProtection: null,
  }), {
    ignoreChecks: ['agent-inbox-clean', 'PR Agent Inbox / Agent inbox'],
  });

  assert.equal(result.clean, false);
  assert.deepEqual(result.checks.failed, ['Template Fitness']);
});

test('unprotected branch metadata treats optional failed checks as optional', () => {
  const branchProtection = fetchBranchProtection({
    json(args) {
      if (args.at(-1).includes('/rules/branches/')) return [];
      throw new Error('gh api repos/o/r/branches/feature/protection failed: gh: Branch not protected (HTTP 404)');
    },
  }, { owner: 'o', name: 'r', branch: 'feature' });

  const result = analyzeInbox(data({
    prView: {
      statusCheckRollup: [
        { name: 'Optional experiment', conclusion: 'FAILURE' },
      ],
    },
    branchProtection,
  }));

  assert.equal(result.clean, true);
  assert.equal(result.nativeProtection.available, true);
});

test('ruleset-only branch metadata is honored after classic protection 404', () => {
  const branchProtection = fetchBranchProtection({
    json(args) {
      if (args.at(-1).includes('/rules/branches/')) {
        return [
          {
            type: 'pull_request',
            parameters: {
              required_approving_review_count: 1,
              required_review_thread_resolution: true,
            },
          },
          {
            type: 'required_status_checks',
            parameters: {
              required_status_checks: [{ context: 'Template Fitness' }],
            },
          },
        ];
      }
      throw new Error('gh api repos/o/r/branches/main/protection failed: gh: Branch not protected (HTTP 404)');
    },
  }, { owner: 'o', name: 'r', branch: 'main' });

  const result = analyzeInbox(data({
    prView: {
      statusCheckRollup: [
        { name: 'Template Fitness', conclusion: 'FAILURE' },
        { name: 'Optional experiment', conclusion: 'FAILURE' },
      ],
    },
    branchProtection,
  }));

  assert.equal(result.nativeProtection.requiredReviews, true);
  assert.equal(result.nativeProtection.requiredConversationResolution, true);
  assert.equal(result.clean, false);
  assert.deepEqual(result.checks.failed, ['Template Fitness']);
});

test('classic branch protection is merged with ruleset-only required checks', () => {
  const branchProtection = fetchBranchProtection({
    json(args) {
      const path = args.at(-1);
      if (path.includes('/protection')) {
        return {
          required_status_checks: { contexts: [] },
          required_pull_request_reviews: { required_approving_review_count: 1 },
        };
      }
      if (path.includes('/rules/branches/')) {
        return [
          {
            type: 'required_status_checks',
            parameters: {
              required_status_checks: [{ context: 'Template Fitness' }],
            },
          },
          {
            type: 'pull_request',
            parameters: {
              required_review_thread_resolution: true,
            },
          },
        ];
      }
      return [];
    },
  }, { owner: 'o', name: 'r', branch: 'main' });

  const result = analyzeInbox(data({
    prView: {
      statusCheckRollup: [
        { name: 'Template Fitness', conclusion: 'FAILURE' },
      ],
    },
    branchProtection,
  }));

  assert.equal(result.nativeProtection.requiredReviews, true);
  assert.equal(result.nativeProtection.requiredConversationResolution, true);
  assert.equal(result.clean, false);
  assert.deepEqual(result.checks.failed, ['Template Fitness']);
});

test('ruleset branch metadata is paginated before required checks are trusted', () => {
  const firstPage = Array.from({ length: 100 }, (_, index) => ({
    type: 'deletion',
    parameters: { index },
  }));
  const branchProtection = fetchBranchProtection({
    json(args) {
      const path = args.at(-1);
      if (path.includes('/protection')) {
        throw new Error('gh api repos/o/r/branches/main/protection failed: gh: Branch not protected (HTTP 404)');
      }
      const page = Number(new URL(`https://example.test/${path}`).searchParams.get('page'));
      if (page === 1) return firstPage;
      if (page === 2) {
        return [
          {
            type: 'required_status_checks',
            parameters: {
              required_status_checks: [{ context: 'Template Fitness' }],
            },
          },
        ];
      }
      return [];
    },
  }, { owner: 'o', name: 'r', branch: 'main' });

  const result = analyzeInbox(data({
    prView: {
      statusCheckRollup: [
        { name: 'Template Fitness', conclusion: 'FAILURE' },
      ],
    },
    branchProtection,
  }));

  assert.equal(result.clean, false);
  assert.deepEqual(result.checks.failed, ['Template Fitness']);
});

test('unavailable branch protection metadata keeps fail-closed check fallback', () => {
  const branchProtection = fetchBranchProtection({
    json() {
      throw new Error('gh api repos/o/r/branches/main/protection failed: gh: Resource not accessible by integration (HTTP 403)');
    },
  }, { owner: 'o', name: 'r', branch: 'main' });

  const result = analyzeInbox(data({
    prView: {
      statusCheckRollup: [
        { name: 'Optional maybe required', conclusion: 'FAILURE' },
      ],
    },
    branchProtection,
  }));

  assert.equal(branchProtection, null);
  assert.equal(result.clean, false);
  assert.deepEqual(result.checks.failed, ['Optional maybe required']);
});

test('classic branch protection is honored when ruleset metadata is unavailable', () => {
  const branchProtection = fetchBranchProtection({
    json(args) {
      const path = args.at(-1);
      if (path.includes('/protection')) {
        return { required_status_checks: { contexts: ['Template Fitness'] } };
      }
      throw new Error('gh api repos/o/r/rules/branches/main failed: gh: Resource not accessible by integration (HTTP 403)');
    },
  }, { owner: 'o', name: 'r', branch: 'main' });

  const result = analyzeInbox(data({
    prView: {
      statusCheckRollup: [
        { name: 'Template Fitness', conclusion: 'FAILURE' },
        { name: 'Optional experiment', conclusion: 'FAILURE' },
      ],
    },
    branchProtection,
  }));

  assert.notEqual(branchProtection, null);
  assert.equal(result.clean, false);
  assert.deepEqual(result.checks.failed, ['Template Fitness']);
});

test('pending checks block locally unless allow-pending-checks is set', () => {
  const blocked = analyzeInbox(data({
    prView: {
      statusCheckRollup: [{ name: 'Template Fitness', status: 'IN_PROGRESS' }],
    },
    branchProtection: {
      required_status_checks: { contexts: ['Template Fitness'] },
    },
  }));

  const allowed = analyzeInbox(data({
    prView: {
      statusCheckRollup: [{ name: 'Template Fitness', status: 'IN_PROGRESS' }],
    },
    branchProtection: {
      required_status_checks: { contexts: ['Template Fitness'] },
    },
  }), { allowPendingChecks: true });

  assert.equal(blocked.clean, false);
  assert.equal(blocked.inboxState, 'waiting');
  assert.equal(blocked.statusState, 'success');
  assert.equal(allowed.clean, true);
});

test('explicit required checks are honored when branch protection omits them', () => {
  const result = analyzeInbox(data({
    prView: {
      statusCheckRollup: [
        { context: 'continuous-integration/jenkins/pr-merge', state: 'PENDING' },
        { name: 'Optional docs', conclusion: 'FAILURE' },
      ],
    },
    branchProtection: {
      required_status_checks: { contexts: [] },
    },
  }), { requiredChecks: ['continuous-integration/jenkins/pr-merge'] });

  assert.equal(result.clean, false);
  assert.equal(result.inboxState, 'waiting');
  assert.equal(result.statusState, 'success');
  assert.deepEqual(result.checks.pending, ['continuous-integration/jenkins/pr-merge']);
  assert.deepEqual(result.checks.failed, []);
});

test('explicit required checks preserve fail-closed behavior when protection is unavailable', () => {
  const result = analyzeInbox(data({
    prView: {
      statusCheckRollup: [
        { context: 'continuous-integration/jenkins/pr-merge', state: 'PENDING' },
        { name: 'Unknown required', conclusion: 'FAILURE' },
      ],
    },
    branchProtection: null,
  }), { requiredChecks: ['continuous-integration/jenkins/pr-merge'] });

  assert.equal(result.clean, false);
  assert.deepEqual(result.checks.pending, ['continuous-integration/jenkins/pr-merge']);
  assert.deepEqual(result.checks.failed, ['Unknown required']);
});

test('branch protection metadata records native review gates', () => {
  const result = analyzeInbox(data({
    branchProtection: {
      required_pull_request_reviews: { required_approving_review_count: 1 },
      required_conversation_resolution: { enabled: true },
    },
  }));

  assert.equal(result.nativeProtection.requiredReviews, true);
  assert.equal(result.nativeProtection.requiredConversationResolution, true);
});

test('markdown includes sticky marker and stable sections', () => {
  const markdown = renderMarkdown(analyzeInbox(data({
    reviewThreads: [thread({ body: 'Fix this thing' })],
  })));

  assert.match(markdown, /<!-- agent-inbox:v1 -->/);
  assert.match(markdown, /# PR Agent Inbox/);
  assert.match(markdown, /Fix this thing/);
});

test('assert-clean is parsed as normalized clean assertion', () => {
  const options = parseArgs(['--pr', '60', '--assert-clean', '--allow-pending-checks', '--required-check', 'continuous-integration/jenkins/pr-merge']);
  assert.equal(options.pr, 60);
  assert.equal(options.assertClean, true);
  assert.equal(options.allowPendingChecks, true);
  assert.deepEqual(options.requiredChecks, ['continuous-integration/jenkins/pr-merge']);
});

test('assert-no-agent-attention is parsed as actionable-only assertion', () => {
  const options = parseArgs(['--pr', '60', '--refresh', '--assert-no-agent-attention']);
  assert.equal(options.pr, 60);
  assert.equal(options.refresh, true);
  assert.equal(options.assertNoAgentAttention, true);
});

test('assert-clean and assert-no-agent-attention cannot be combined', () => {
  assert.throws(() => parseArgs(['--pr', '60', '--assert-clean', '--assert-no-agent-attention']), {
    message: '--assert-clean and --assert-no-agent-attention are mutually exclusive',
  });
});

test('exit policy distinguishes waiting state from agent attention', () => {
  assert.equal(shouldExitNonzero({
    clean: false,
    agentAttention: false,
  }, {
    assertClean: true,
  }), true);

  assert.equal(shouldExitNonzero({
    clean: false,
    agentAttention: false,
  }, {
    assertNoAgentAttention: true,
  }), false);

  assert.equal(shouldExitNonzero({
    clean: false,
    agentAttention: true,
  }, {
    assertNoAgentAttention: true,
  }), true);

  assert.equal(shouldExitNonzero({
    clean: true,
    agentAttention: false,
  }, {
    assertNoAgentAttention: true,
  }, [{ name: 'publish inbox status' }]), true);

  assert.equal(shouldExitNonzero({
    clean: true,
    agentAttention: false,
  }, {
    assertNoAgentAttention: true,
  }, [{ name: 'update sticky inbox comment' }]), false);
});

test('refresh exits zero for ordinary agent attention but not status publish failures', () => {
  const result = { clean: false, agentAttention: true };
  assert.equal(shouldExitNonzero(result, { refresh: true, assertNoAgentAttention: true }), false);
  assert.equal(shouldExitNonzero(result, { refresh: true }, [{ name: 'publish inbox status' }]), true);
});

test('label sync adds and removes based on agentAttention', () => {
  const client = fakeClient();
  syncAttentionLabel(client, { repo: 'owner/repo', pr: 1, agentAttention: true }, defaultAttentionLabel);
  syncAttentionLabel(client, { repo: 'owner/repo', pr: 1, agentAttention: false }, defaultAttentionLabel);

  assert.deepEqual(client.calls.map((call) => call.args.slice(0, 5)), [
    ['api', '-X', 'POST', 'repos/owner/repo/issues/1/labels', '-f'],
    ['api', '-X', 'DELETE', 'repos/owner/repo/issues/1/labels/agent-attention'],
  ]);
});

test('label provisioning is idempotent for already-existing labels', () => {
  const client = fakeClient();
  ensureLabel(client, 'owner/repo', defaultAttentionLabel);

  assert.equal(client.calls[0].options.allowError, true);
  assert.deepEqual(client.calls[0].args.slice(0, 4), ['api', '-X', 'POST', 'repos/owner/repo/labels']);
});

test('status publishing writes durable state to the PR head commit', () => {
  const client = fakeClient();
  publishStatus(client, {
    repo: 'owner/repo',
    pr: 1,
    url: 'https://github.com/owner/repo/pull/1',
    headRefOid: 'abc123',
    statusState: 'failure',
    statusDescription: '1 agent-actionable item(s)',
  });

  const post = client.calls.find((call) => call.args.includes('repos/owner/repo/statuses/abc123'));
  assert.ok(post);
  assert.deepEqual(post.args.slice(0, 4), ['api', '-X', 'POST', 'repos/owner/repo/statuses/abc123']);
  assert.ok(post.args.includes('state=failure'));
  assert.ok(post.args.includes('context=agent-inbox-clean'));
});

test('status publishing skips unchanged head status', () => {
  const client = fakeClient({
    responses: {
      'repos/owner/repo/commits/abc123/statuses': [
        { context: 'agent-inbox-clean', state: 'success', description: 'PR agent inbox is clean' },
      ],
    },
  });

  const outcome = publishStatus(client, {
    repo: 'owner/repo',
    pr: 1,
    url: 'https://github.com/owner/repo/pull/1',
    headRefOid: 'abc123',
    statusState: 'success',
    statusDescription: 'PR agent inbox is clean',
  });

  assert.deepEqual(outcome, { skipped: true });
  assert.equal(client.calls.some((call) => call.args.includes('repos/owner/repo/statuses/abc123')), false);
});

test('sticky comment updates the newest well-formed inbox report', () => {
  const client = fakeClient({
    responses: {
      'repos/owner/repo/issues/1/comments?per_page=100&page=1': [
        { id: 11, body: '<!-- agent-inbox:v1 -->\nordinary comment', user: { login: 'reviewer' } },
        { id: 12, body: '<!-- agent-inbox:v1 -->\n# PR Agent Inbox\nold report', user: { login: 'github-actions[bot]' } },
        {
          id: 13,
          body: '<!-- agent-inbox:v1 -->\n# PR Agent Inbox\nnewer report',
          user: { login: 'rbudnar' },
          author_association: 'OWNER',
        },
      ],
    },
  });

  updateStickyComment(client, {
    repo: 'owner/repo',
    pr: 1,
    clean: true,
    agentAttention: false,
    statusState: 'success',
    items: [],
    nativeProtection: {},
  });

  const patch = client.calls.find((call) => call.args.includes('repos/owner/repo/issues/comments/13'));
  assert.ok(patch);
  assert.equal(client.calls.some((call) => call.args.includes('repos/owner/repo/issues/comments/11')), false);
  assert.equal(client.calls.some((call) => call.args.includes('repos/owner/repo/issues/comments/12')), false);
});

test('sticky comment ignores untrusted marker spoof comments', () => {
  const client = fakeClient({
    responses: {
      'repos/owner/repo/issues/1/comments?per_page=100&page=1': [
        { id: 12, body: '<!-- agent-inbox:v1 -->\n# PR Agent Inbox\ntrusted report', user: { login: 'github-actions[bot]' } },
        {
          id: 13,
          body: '<!-- agent-inbox:v1 -->\n# PR Agent Inbox\nspoofed report',
          user: { login: 'outside-contributor' },
          author_association: 'CONTRIBUTOR',
        },
      ],
    },
  });

  updateStickyComment(client, {
    repo: 'owner/repo',
    pr: 1,
    clean: true,
    agentAttention: false,
    statusState: 'success',
    items: [],
    nativeProtection: {},
  });

  const patch = client.calls.find((call) => call.args.includes('repos/owner/repo/issues/comments/12'));
  assert.ok(patch);
  assert.equal(client.calls.some((call) => call.args.includes('repos/owner/repo/issues/comments/13')), false);
});

test('sticky comment update failure does not create a duplicate inbox report', () => {
  const denied = new Error('gh: Resource not accessible by integration (HTTP 403)');
  const client = fakeClient({
    responses: {
      'repos/owner/repo/issues/1/comments?per_page=100&page=1': [
        {
          id: 13,
          body: '<!-- agent-inbox:v1 -->\n# PR Agent Inbox\nnewer report',
          user: { login: 'rbudnar' },
          author_association: 'OWNER',
        },
      ],
      'repos/owner/repo/issues/comments/13': denied,
    },
  });
  const warnings = [];

  const failures = publishInboxSideEffects(client, {
    repo: 'owner/repo',
    pr: 1,
    clean: true,
    agentAttention: false,
    statusState: 'success',
    items: [],
    nativeProtection: {},
  }, {
    updateComment: true,
  }, {
    onWarning: (message) => warnings.push(message),
  });

  assert.equal(failures.length, 1);
  assert.match(warnings[0], /update sticky inbox comment failed/);
  assert.equal(
    client.calls.some((call) => call.args.includes('-X')
      && call.args.includes('POST')
      && call.args.includes('repos/owner/repo/issues/1/comments')),
    false,
  );
});

test('publishing side effects continue when write permissions are unavailable', () => {
  const denied = new Error('gh: Resource not accessible by integration (HTTP 403)');
  const client = fakeClient({
    responses: {
      'repos/owner/repo/issues/1/comments?per_page=100&page=1': [],
      'repos/owner/repo/issues/1/comments': denied,
      'repos/owner/repo/commits/abc123/statuses': [],
      'repos/owner/repo/statuses/abc123': denied,
    },
  });
  const warnings = [];

  const failures = publishInboxSideEffects(client, {
    repo: 'owner/repo',
    pr: 1,
    headRefOid: 'abc123',
    clean: false,
    agentAttention: false,
    inboxState: 'waiting',
    statusState: 'success',
    statusDescription: 'No agent-actionable inbox items',
    items: [],
    nativeProtection: {},
  }, {
    updateComment: true,
    publishStatus: true,
    statusContext: 'agent-inbox-clean',
  }, {
    onWarning: (message) => warnings.push(message),
  });

  assert.equal(failures.length, 2);
  assert.equal(warnings.length, 2);
  assert.match(warnings[0], /update sticky inbox comment failed/);
  assert.match(warnings[1], /publish inbox status failed/);
  assert.ok(client.calls.some((call) => call.args.includes('repos/owner/repo/statuses/abc123')));
});

test('canonical inbox workflow and signal checks are ignored by exact identity when protection is unavailable', () => {
  const ignoreChecks = [
    'agent-inbox-clean',
    'PR Agent Inbox / agent-inbox',
    'PR Agent Inbox Signal / Agent inbox',
  ];
  for (const conclusion of ['ACTION_REQUIRED', 'TIMED_OUT', 'CANCELLED']) {
    const result = analyzeInbox(data({
      prView: {
        statusCheckRollup: [
          { workflowName: 'PR Agent Inbox Signal', name: 'Agent inbox', conclusion },
        ],
      },
      branchProtection: null,
    }), { ignoreChecks });

    assert.equal(result.clean, true, `${conclusion} signal plumbing is not agent work`);
    assert.deepEqual(result.checks.failed, []);
  }
});

test('ignored status contexts and workflow/job tuples do not collide across identity fields', () => {
  const ignoreChecks = [
    'agent-inbox-clean',
    'PR Agent Inbox / agent-inbox',
    'PR Agent Inbox Signal / Agent inbox',
  ];
  const collisions = [
    { workflowName: 'agent-inbox-clean', name: 'attacker-job', conclusion: 'FAILURE' },
    { context: 'PR Agent Inbox Signal / Agent inbox', conclusion: 'FAILURE' },
    { workflowName: 'PR Agent Inbox Signal', name: 'attacker-job', conclusion: 'FAILURE' },
    { workflowName: 'attacker-workflow', name: 'Agent inbox', conclusion: 'FAILURE' },
    { workflowName: 'PR Agent Inbox Signalling', name: 'Agent inbox', conclusion: 'FAILURE' },
  ];

  for (const check of collisions) {
    const result = analyzeInbox(data({
      prView: { statusCheckRollup: [check] },
      branchProtection: null,
    }), { ignoreChecks });
    assert.equal(result.clean, false, JSON.stringify(check));
    assert.equal(result.checks.failed.length, 1, JSON.stringify(check));
  }
});

test('permissionless signal owns the exact review events and one bounded hosted no-op', () => {
  const workflow = signalWorkflow();
  const events = yamlTopLevelBlock(workflow, 'on');
  const jobs = workflowJobs(workflow);

  assert.match(workflow, /^name:\s*PR Agent Inbox Signal\s*$/m);
  assert.deepEqual(workflowEventNames(events).sort(), [
    'pull_request_review', 'pull_request_review_comment',
  ]);
  assert.deepEqual(workflowEventTypes(events, 'pull_request_review'), ['submitted', 'edited', 'dismissed']);
  assert.deepEqual(workflowEventTypes(events, 'pull_request_review_comment'), ['created', 'edited', 'deleted']);
  assert.match(workflow, /^permissions:\s*\{\}\s*$/m);
  assert.equal(jobs.length, 1);
  assert.match(jobs[0].body, /^    name:\s*Agent inbox\s*$/m);
  assert.match(jobs[0].body, /^    runs-on:\s*ubuntu-latest\s*$/m);
  assert.match(jobs[0].body, /^    timeout-minutes:\s*5\s*$/m);
  assert.equal([...jobs[0].body.matchAll(/^      -\s+(?:name|run|uses):/gm)].length, 1);
  assert.match(jobs[0].body, /^(?:      - run|        run):\s*[^|>\n]+$/m);
  assert.doesNotMatch(workflow, /\$\{\{|\buses:|\benv:|\boutputs:|\bpermissions:\s*\n|\b(?:gh|curl|wget)\b|checkout|artifact|cache|secrets?/i);
});

test('privileged workflow owns only exact direct, manual, and five completed workflow-run events', () => {
  const workflow = inboxWorkflow();
  const events = yamlTopLevelBlock(workflow, 'on');

  assert.deepEqual(workflowEventNames(events).sort(), [
    'issue_comment', 'pull_request_target', 'workflow_dispatch', 'workflow_run',
  ]);
  assert.deepEqual(workflowEventTypes(events, 'pull_request_target'), [
    'opened', 'edited', 'reopened', 'synchronize', 'ready_for_review', 'converted_to_draft', 'closed',
  ]);
  assert.deepEqual(workflowEventTypes(events, 'issue_comment'), ['created']);
  assert.deepEqual(workflowEventTypes(events, 'workflow_run'), ['completed']);
  assert.deepEqual(workflowRunProducers(events), [
    'check-drift', 'protect-protocol', 'validate-examples', 'validate-ledger', 'PR Agent Inbox Signal',
  ]);
  assert.match(workflow, /^permissions:\s*\{\}\s*$/m);
});

test('workflow-run routing authenticates canonical current workflow identity and provenance without producer data', () => {
  const workflow = inboxWorkflow();
  const resolver = workflowJobs(workflow).find(({ body }) => body.includes('workflow_run')
    && body.includes('pull_requests'));
  const mappings = new Map([
    ['check-drift', '.github/workflows/check-drift.yml'],
    ['protect-protocol', '.github/workflows/protect-protocol.yml'],
    ['validate-examples', '.github/workflows/validate-examples.yml'],
    ['validate-ledger', '.github/workflows/validate-ledger.yml'],
    ['PR Agent Inbox Signal', '.github/workflows/pr-agent-inbox-signal.yml'],
  ]);

  assert.ok(resolver, 'a read-only workflow_run resolver must own producer admission');
  assert.match(resolver.body, /repos\/.+\/actions\/workflows|actions\/workflows\//);
  for (const [name, path] of mappings) {
    assert.match(resolver.body, new RegExp(escapeRegex(name)));
    assert.match(resolver.body, new RegExp(escapeRegex(path)));
  }
  for (const field of ['workflow_id', 'path', 'repository.full_name', 'event', 'head_sha', 'pull_requests']) {
    assert.match(resolver.body, new RegExp(escapeRegex(field)));
  }
  assert.match(resolver.body, /pull_request_review_comment/);
  assert.match(resolver.body, /pull_request_review/);
  assert.match(resolver.body, /pull_request/);
  assert.match(resolver.body, /\[0-9a-fA-F\]\{40\}/);
  assert.match(resolver.body, /--paginate/);
  assert.doesNotMatch(resolver.body, /<\s*\(/, 'API failures must not be hidden by process substitution');
  assert.doesNotMatch(workflow, /download-artifact|upload-artifact|actions\/cache|cache-dependency-path|\/artifacts|\/logs/i);
});

test('comment and dispatch routing admit only exact commands, numeric PRs, and a bounded draft-inclusive blank sweep', () => {
  const workflow = inboxWorkflow();
  const jobs = workflowJobs(workflow);
  const comment = jobs.find(({ body }) => body.includes('/agent-inbox refresh')
    && body.includes('/collaborators/') && body.includes('/permission'));
  const dispatch = jobs.find(({ body }) => body.includes('workflow_dispatch')
    && body.includes('github.ref_name') && body.includes('default_branch'));

  assert.ok(comment, 'read-only comment authorization must precede publication');
  assert.match(comment.body, /\.trim\(\)/);
  assert.match(comment.body, /\/agent-inbox refresh/);
  assert.doesNotMatch(comment.body, /startsWith\s*\(/);
  assert.match(comment.body, /admin\|maintain\|write/);
  assert.doesNotMatch(comment.body, /actions\/checkout|\b(?:issues|pull-requests|statuses):\s*write\b/);

  assert.ok(dispatch, 'read-only dispatch routing must precede publication');
  assert.match(dispatch.body, /github\.ref_name/);
  assert.match(dispatch.body, /github\.event\.repository\.default_branch/);
  assert.match(dispatch.body, /\^\[1-9\]\[0-9\]\*\$/);
  assert.match(dispatch.body, /(?:^|\D)100(?:\D|$)/);
  assert.match(dispatch.body, /isDraft|\.draft/);
  assert.doesNotMatch(dispatch.body, /!\s*(?:pr\.)?(?:isDraft|draft)/);
  assert.match(workflow, /--refresh\b/);
});

test('all routes converge on read-only admission and a non-cancelling immutable-base publisher', () => {
  const workflow = inboxWorkflow();
  const jobs = workflowJobs(workflow);
  const publishers = jobs.filter(({ body }) => body.includes('scripts/pr-agent-inbox.mjs'));

  assert.ok(publishers.length > 0, 'admitted PR identities must reach a publisher');
  for (const { name, body } of jobs) {
    assert.match(body, /^    runs-on:\s*ubuntu-latest\s*$/m, `${name} must be hosted`);
    assert.match(body, /^    timeout-minutes:\s*5\s*$/m, `${name} must be bounded`);
    if (!body.includes('scripts/pr-agent-inbox.mjs')) {
      assert.doesNotMatch(body, /\b(?:issues|pull-requests|statuses):\s*write\b/, `${name} must stay read-only`);
      assert.doesNotMatch(body, /actions\/checkout/, `${name} must not checkout`);
      continue;
    }

    for (const permission of ['contents: read', 'pull-requests: write', 'issues: write', 'statuses: write']) {
      assert.match(body, new RegExp(escapeRegex(permission)));
    }
    assert.match(body, /group:\s*pr-agent-inbox-pr-/);
    assert.match(body, /cancel-in-progress:\s*false/);
    assert.match(body, /state/);
    assert.match(body, /isDraft/);
    assert.match(body, /baseRefName/);
    assert.match(body, /headRefOid/);
    assert.match(body, /isCrossRepository/);
    assert.match(body, /default_branch/);
    assert.match(body, /\[0-9a-fA-F\]\{40\}/);
    assert.match(body, /ref:\s*\$\{\{[^}]*default[^}]*oid[^}]*\}\}/i);
    assert.match(body, /persist-credentials:\s*false/);
    assert.deepEqual(ignoreCheckArguments(body), [
      'agent-inbox-clean',
      'PR Agent Inbox / agent-inbox',
      'PR Agent Inbox Signal / Agent inbox',
    ]);
  }

  assert.match(workflow, /fromJSON\(/);
  assert.doesNotMatch(workflow, /schedule:|^  status:|^  check_run:|repository_dispatch:|pull_request_review_thread:/m);
  assert.doesNotMatch(workflow, /self-hosted|rbudnar-linux|open-autoresearch-inbox/i);
  assert.doesNotMatch(workflow, /download-artifact|upload-artifact|actions\/cache|cache-dependency-path|github\.sha|pull_request\.head|head\.sha/i);
});

function data(overrides = {}) {
  return {
    repo: 'owner/repo',
    pr: 60,
    prView: {
      number: 60,
      url: 'https://github.com/owner/repo/pull/60',
      title: 'Example PR',
      isDraft: false,
      reviewDecision: null,
      mergeStateStatus: 'CLEAN',
      statusCheckRollup: [],
      latestReviews: [],
      headRefOid: 'abc123',
      headRefName: 'feature',
      baseRefName: 'main',
      ...(overrides.prView ?? {}),
    },
    reviewThreads: overrides.reviewThreads ?? [],
    reviewComments: overrides.reviewComments ?? [],
    issueComments: overrides.issueComments ?? [],
    reviews: overrides.reviews ?? [],
    branchProtection: Object.hasOwn(overrides, 'branchProtection') ? overrides.branchProtection : {
      required_status_checks: { contexts: [] },
    },
  };
}

function thread(overrides = {}) {
  return {
    id: overrides.id ?? 'thread-1',
    isResolved: overrides.isResolved ?? false,
    isOutdated: overrides.isOutdated ?? false,
    comments: {
      nodes: [
        {
          id: 'comment-1',
          url: 'https://example/thread',
          body: overrides.body ?? 'Please fix this.',
          author: { login: 'reviewer' },
        },
      ],
    },
  };
}

function fakeClient({ responses = {} } = {}) {
  return {
    calls: [],
    json(args, callOptions = {}) {
      this.calls.push({ method: 'json', args, options: callOptions });
      const key = args.includes('graphql')
        ? 'graphql'
        : (args.find((arg) => Object.hasOwn(responses, arg)) ?? args.at(-1));
      if (Object.hasOwn(responses, key)) {
        if (responses[key] instanceof Error) throw responses[key];
        return responses[key];
      }
      return {};
    },
    text(args, callOptions = {}) {
      this.calls.push({ method: 'text', args, options: callOptions });
      return '';
    },
  };
}

function inboxWorkflow() {
  return readFileSync(new URL('../.github/workflows/pr-agent-inbox.yml', import.meta.url), 'utf8');
}

function signalWorkflow() {
  return readFileSync(new URL('../.github/workflows/pr-agent-inbox-signal.yml', import.meta.url), 'utf8');
}

function yamlTopLevelBlock(source, key) {
  const match = new RegExp(`^${escapeRegex(key)}:\\s*(?:\\n|$)`, 'm').exec(source);
  assert.ok(match, `workflow must define ${key}`);
  const rest = source.slice(match.index + match[0].length);
  const next = /^[A-Za-z][A-Za-z0-9_-]*:\s*(?:\n|$)/m.exec(rest);
  return rest.slice(0, next?.index ?? rest.length);
}

function workflowEventTypes(events, event) {
  const eventBlock = yamlIndentedBlock(events, event, 2);
  const match = /^    types:\s*\[([^\]]*)\]/m.exec(eventBlock);
  if (match) return match[1].split(',').map((value) => value.trim()).filter(Boolean);
  const block = /^    types:\s*\n((?:\s{6}-\s*[^\n]+\n)+)/m.exec(eventBlock);
  assert.ok(block, `${event} must have an explicit type allowlist`);
  return [...block[1].matchAll(/^\s{6}-\s*(.+)$/gm)].map((entry) => entry[1].trim());
}

function workflowEventNames(events) {
  return [...events.matchAll(/^  ([A-Za-z][A-Za-z0-9_]*):/gm)].map((entry) => entry[1]);
}

function workflowRunProducers(events) {
  const eventBlock = yamlIndentedBlock(events, 'workflow_run', 2);
  const match = /^    workflows:\s*\n((?:\s{6}-\s*[^\n]+\n)+)/m.exec(eventBlock);
  assert.ok(match, 'workflow_run must list its producer workflows');
  return [...match[1].matchAll(/^\s{6}-\s*(.+)$/gm)].map((entry) => entry[1].trim());
}

function yamlIndentedBlock(source, key, indent) {
  const spaces = ' '.repeat(indent);
  const match = new RegExp(`^${spaces}${escapeRegex(key)}:\\s*\\n`, 'm').exec(source);
  assert.ok(match, `${key} must be present`);
  const rest = source.slice(match.index + match[0].length);
  const next = new RegExp(`^${spaces}[A-Za-z][A-Za-z0-9_-]*:\\s*(?:\\n|$)`, 'm').exec(rest);
  return rest.slice(0, next?.index ?? rest.length);
}

function workflowJobs(workflow) {
  const jobs = yamlTopLevelBlock(workflow, 'jobs');
  return [...jobs.matchAll(/^  ([A-Za-z][A-Za-z0-9_-]*):\n([\s\S]*?)(?=^  [A-Za-z][A-Za-z0-9_-]*:\n|$(?![\s\S]))/gm)]
    .map((entry) => ({ name: entry[1], body: entry[2] }));
}

function ignoreCheckArguments(job) {
  return [...job.matchAll(/--ignore-check\s+(?:"([^"]+)"|'([^']+)'|([^\s\\]+))/g)]
    .map((entry) => entry[1] ?? entry[2] ?? entry[3]);
}

function escapeRegex(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}
