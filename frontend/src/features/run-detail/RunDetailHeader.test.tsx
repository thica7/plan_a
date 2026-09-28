import { render, screen } from '@testing-library/react';
import { expect, it } from 'vitest';
import type { RunDetail } from '../../api/types';
import { RunDetailHeader } from './RunDetailHeader';

it('shows the target product and its homepage verification state', () => {
  const detail = {
    topic: '寻找同类产品', status: 'running', execution_mode: 'real',
    plan: {
      target_product: { name: '示例无线吸尘器', category: '家用清洁电器' },
      target_product_evidence: {
        status: 'verified', source_url: 'https://example.com/vacuum',
        title: '示例无线吸尘器官网',
      },
      competitors: ['洁净家'], dimensions: ['feature'], competitor_layer: 'L1',
      homepage_verified: { '示例无线吸尘器': false },
      scenario_id: 'product-example', qa_rule_ids: [], task_decomposition: [],
    },
  } as unknown as RunDetail;
  render(<RunDetailHeader detail={detail} recommendedDimensions={[]} />);
  expect(screen.getByText('示例无线吸尘器')).toBeInTheDocument();
  expect(screen.getByRole('link', { name: /官网待核验/ })).toHaveAttribute('href', 'https://example.com/vacuum');
});

it('links a verified homepage instead of labeling a review page as official', () => {
  const detail = {
    topic: 'Notion research', status: 'running', execution_mode: 'real',
    plan: {
      target_product: { name: 'Notion', category: 'team software' },
      target_product_evidence: {
        status: 'verified', source_url: 'https://reviews.example/notion-review',
      },
      homepage_verified: { Notion: true },
      homepage_hints: { Notion: 'https://notion.so' },
      competitors: ['Notion', 'Other'], dimensions: ['feature'],
      competitor_layer: 'L1', scenario_id: null, qa_rule_ids: [], task_decomposition: [],
    },
  } as unknown as RunDetail;
  render(<RunDetailHeader detail={detail} recommendedDimensions={[]} />);
  expect(screen.getByRole('link', { name: '官网已核验' })).toHaveAttribute('href', 'https://notion.so');
});
