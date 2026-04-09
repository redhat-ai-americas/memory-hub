import React from 'react';
import {
  Alert,
  Button,
  ClipboardCopy,
  ClipboardCopyVariant,
  Content,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  Title,
} from '@patternfly/react-core';
import { renderWelcomeEmail } from './welcomeEmail';

interface SecretRevealModalProps {
  isOpen: boolean;
  clientId: string;
  clientName: string;
  clientSecret: string;
  tenantId: string;
  scopes: string[];
  mcpUrl: string;
  authUrl: string;
  onClose: () => void;
}

/**
 * Shown after an OAuth client is created or its secret is rotated.
 *
 * The modal has two copy targets:
 *
 *   1. The raw client secret (one-time visible, must be copied immediately
 *      or it is lost — the server hashes it on creation and cannot recover).
 *   2. A fully-formatted welcome email body the maintainer can paste into
 *      their email client to send to the contributor. The email body embeds
 *      the same secret, so if the maintainer only copies the email they
 *      still have everything they need.
 *
 * The email template lives in ./welcomeEmail.ts as a pure function so the
 * rendering logic is easy to audit and test.
 */
const SecretRevealModal: React.FC<SecretRevealModalProps> = ({
  isOpen,
  clientId,
  clientName,
  clientSecret,
  tenantId,
  scopes,
  mcpUrl,
  authUrl,
  onClose,
}) => {
  const emailBody = renderWelcomeEmail({
    clientId,
    clientName,
    clientSecret,
    tenantId,
    scopes,
    mcpUrl,
    authUrl,
  });

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      variant="medium"
      aria-label="Client secret and welcome email"
    >
      <ModalHeader title={`Credentials for ${clientId}`} />
      <ModalBody>
        <Alert
          variant="warning"
          isInline
          isPlain
          title="Copy the secret now — it will not be shown again."
          style={{ marginBottom: '1rem' }}
        />

        <Title headingLevel="h3" size="md" style={{ marginBottom: '0.5rem' }}>
          Client secret
        </Title>
        <ClipboardCopy isReadOnly hoverTip="Copy secret" clickTip="Copied" variant={ClipboardCopyVariant.expansion}>
          {clientSecret}
        </ClipboardCopy>

        <Title
          headingLevel="h3"
          size="md"
          style={{ marginTop: '1.5rem', marginBottom: '0.5rem' }}
        >
          Welcome email
        </Title>
        <Content component="small" style={{ color: 'var(--pf-v6-global--Color--200)', display: 'block', marginBottom: '0.5rem' }}>
          Paste this into a new email to the contributor. It includes the client ID, secret, tenant, scopes, MCP/auth URLs, and pointers to CONTRIBUTING and the cluster-access policy.
        </Content>
        <ClipboardCopy
          isReadOnly
          hoverTip="Copy email body"
          clickTip="Copied"
          variant={ClipboardCopyVariant.expansion}
          isExpanded
          isCode
        >
          {emailBody}
        </ClipboardCopy>
      </ModalBody>
      <ModalFooter>
        <Button variant="primary" onClick={onClose}>
          Done
        </Button>
      </ModalFooter>
    </Modal>
  );
};

export default SecretRevealModal;
