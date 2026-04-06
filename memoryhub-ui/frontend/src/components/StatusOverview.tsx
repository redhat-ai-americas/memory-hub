import React, { useEffect, useState } from 'react';
import {
  Alert,
  Card,
  CardBody,
  CardTitle,
  Content,
  DescriptionList,
  DescriptionListDescription,
  DescriptionListGroup,
  DescriptionListTerm,
  Flex,
  FlexItem,
  Grid,
  GridItem,
  Spinner,
  Stack,
  StackItem,
  Title,
} from '@patternfly/react-core';
import { CheckCircleIcon, ExclamationCircleIcon } from '@patternfly/react-icons';
import { ChartDonut } from '@patternfly/react-charts/victory';
import type { StatsResponse } from '@/types';
import { fetchStats } from '@/api/client';
import ScopeBadge from './ScopeBadge';
import { SCOPE_COLORS } from '@/utils/scopes';
import { formatRelativeTime } from '@/utils/time';

const StatusOverview: React.FC = () => {
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchStats()
      .then((data) => setStats(data))
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : 'Failed to load stats');
      })
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <Flex justifyContent={{ default: 'justifyContentCenter' }} style={{ padding: '4rem' }}>
        <Spinner size="xl" />
      </Flex>
    );
  }

  if (error) {
    return (
      <div style={{ padding: '1rem' }}>
        <Alert variant="danger" title="Failed to load stats" isInline>
          {error}
        </Alert>
      </div>
    );
  }

  if (!stats) return null;

  const donutData = stats.scope_counts.map((sc) => ({
    x: sc.scope,
    y: sc.count,
  }));

  const scopeBreakdown = stats.scope_counts
    .map((sc) => `${sc.count} ${sc.scope}`)
    .join(', ');

  return (
    <div style={{ padding: '1.5rem', overflow: 'auto', height: '100%' }}>
      <Grid hasGutter>
        {/* Card 1: Total Memories */}
        <GridItem sm={12} md={6}>
          <Card isFullHeight>
            <CardTitle>
              <Title headingLevel="h3" size="md">
                Total Memories
              </Title>
            </CardTitle>
            <CardBody>
              <Stack>
                <StackItem>
                  <p
                    style={{
                      fontSize: '3.5rem',
                      fontWeight: 700,
                      lineHeight: 1,
                      color: 'var(--pf-v6-global--primary-color--100)',
                      margin: 0,
                    }}
                  >
                    {stats.total_memories.toLocaleString()}
                  </p>
                </StackItem>
                <StackItem>
                  <Content component="small" style={{ color: 'var(--pf-v6-global--Color--200)' }}>
                    {scopeBreakdown || 'No memories yet'}
                  </Content>
                </StackItem>
              </Stack>
            </CardBody>
          </Card>
        </GridItem>

        {/* Card 2: Memories by Scope (donut chart) */}
        <GridItem sm={12} md={6}>
          <Card isFullHeight>
            <CardTitle>
              <Title headingLevel="h3" size="md">
                Memories by Scope
              </Title>
            </CardTitle>
            <CardBody>
              {donutData.length > 0 ? (
                <Flex
                  alignItems={{ default: 'alignItemsCenter' }}
                  gap={{ default: 'gapLg' }}
                >
                  <FlexItem>
                    <ChartDonut
                      data={donutData}
                      colorScale={donutData.map((d) => SCOPE_COLORS[d.x] ?? '#6A6E73')}
                      height={180}
                      width={180}
                      innerRadius={55}
                      labels={({ datum }: { datum: { x: string; y: number } }) => `${datum.x}: ${datum.y}`}
                      title={String(stats.total_memories)}
                      subTitle="memories"
                    />
                  </FlexItem>
                  <FlexItem>
                    <Stack hasGutter>
                      {stats.scope_counts.map((sc) => (
                        <StackItem key={sc.scope}>
                          <Flex alignItems={{ default: 'alignItemsCenter' }} gap={{ default: 'gapSm' }}>
                            <FlexItem>
                              <ScopeBadge scope={sc.scope} />
                            </FlexItem>
                            <FlexItem>
                              <Content component="small">
                                {sc.count} ({stats.total_memories > 0 ? Math.round((sc.count / stats.total_memories) * 100) : 0}%)
                              </Content>
                            </FlexItem>
                          </Flex>
                        </StackItem>
                      ))}
                    </Stack>
                  </FlexItem>
                </Flex>
              ) : (
                <Content component="small" style={{ color: 'var(--pf-v6-global--Color--200)' }}>
                  No scope data available.
                </Content>
              )}
            </CardBody>
          </Card>
        </GridItem>

        {/* Card 3: Recent Activity */}
        <GridItem sm={12} md={6}>
          <Card isFullHeight>
            <CardTitle>
              <Title headingLevel="h3" size="md">
                Recent Activity
              </Title>
            </CardTitle>
            <CardBody>
              {stats.recent_activity.length > 0 ? (
                <Stack hasGutter>
                  {stats.recent_activity.slice(0, 10).map((activity) => (
                    <StackItem key={activity.id}>
                      <Flex alignItems={{ default: 'alignItemsCenter' }} gap={{ default: 'gapSm' }}>
                        <FlexItem>
                          <ScopeBadge scope={activity.scope} />
                        </FlexItem>
                        <FlexItem grow={{ default: 'grow' }} style={{ minWidth: 0 }}>
                          <Content
                            component="small"
                            style={{
                              overflow: 'hidden',
                              textOverflow: 'ellipsis',
                              whiteSpace: 'nowrap',
                              display: 'block',
                            }}
                            title={activity.stub}
                          >
                            {activity.stub}
                          </Content>
                        </FlexItem>
                        <FlexItem style={{ flexShrink: 0 }}>
                          <Content component="small" style={{ color: 'var(--pf-v6-global--Color--200)' }}>
                            {formatRelativeTime(activity.updated_at)}
                          </Content>
                        </FlexItem>
                      </Flex>
                    </StackItem>
                  ))}
                </Stack>
              ) : (
                <Content component="small" style={{ color: 'var(--pf-v6-global--Color--200)' }}>
                  No recent activity.
                </Content>
              )}
            </CardBody>
          </Card>
        </GridItem>

        {/* Card 4: MCP Server Health */}
        <GridItem sm={12} md={6}>
          <Card isFullHeight>
            <CardTitle>
              <Title headingLevel="h3" size="md">
                MCP Server Health
              </Title>
            </CardTitle>
            <CardBody>
              <Stack hasGutter>
                <StackItem>
                  <Flex alignItems={{ default: 'alignItemsCenter' }} gap={{ default: 'gapMd' }}>
                    <FlexItem>
                      {stats.mcp_health ? (
                        <CheckCircleIcon
                          style={{ color: '#3E8635', fontSize: '2.5rem' }}
                        />
                      ) : (
                        <ExclamationCircleIcon
                          style={{ color: '#C9190B', fontSize: '2.5rem' }}
                        />
                      )}
                    </FlexItem>
                    <FlexItem>
                      <p
                        style={{
                          fontWeight: 600,
                          color: stats.mcp_health ? '#3E8635' : '#C9190B',
                          margin: 0,
                        }}
                      >
                        {stats.mcp_health ? 'Healthy' : 'Unhealthy'}
                      </p>
                      <Content component="small" style={{ color: 'var(--pf-v6-global--Color--200)' }}>
                        {stats.mcp_health
                          ? 'MCP server is responding normally'
                          : 'MCP server is not responding — check deployment logs'}
                      </Content>
                    </FlexItem>
                  </Flex>
                </StackItem>

                <StackItem>
                  <DescriptionList isCompact isHorizontal>
                    <DescriptionListGroup>
                      <DescriptionListTerm>Status</DescriptionListTerm>
                      <DescriptionListDescription>
                        {stats.mcp_health ? 'Online' : 'Offline'}
                      </DescriptionListDescription>
                    </DescriptionListGroup>
                  </DescriptionList>
                </StackItem>
              </Stack>
            </CardBody>
          </Card>
        </GridItem>
      </Grid>
    </div>
  );
};

export default StatusOverview;
