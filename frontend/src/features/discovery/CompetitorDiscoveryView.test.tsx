import { render, screen } from '@testing-library/react';
import { expect, it } from 'vitest';
import { CompetitorDiscoveryView } from './CompetitorDiscoveryView';

it('distinguishes supported direct rivals from candidates needing verification', () => {
  render(<CompetitorDiscoveryView discovery={{
    query: '家用清洁产品', search_queries: ['家用清洁产品', '无线吸尘器替代方案'],
    selected_competitors: ['洁净家'], rationale: '同类产品', created_at: '2026-09-28',
    candidates: [
      { name: '洁净家', rank: 1, selected: true, relationship: 'direct', rationale: '相同家庭清洁任务',
        evidence_urls: ['https://example.com/clean'], evidence_titles: ['洁净家产品说明'], confidence: 0.8 },
      { name: '无证品牌', rank: 2, selected: false, relationship: 'unverified', rationale: '资料不足',
        evidence_urls: [], evidence_titles: [], confidence: 0.3 },
    ],
  }} />);
  expect(screen.getByText('直接竞品')).toBeInTheDocument();
  expect(screen.getByText('待核验')).toBeInTheDocument();
  expect(screen.getByRole('link', { name: '洁净家产品说明' })).toHaveAttribute('href', 'https://example.com/clean');
});
