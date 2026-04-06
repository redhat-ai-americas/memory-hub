import React from 'react';
import {
  Alert,
  Button,
  ClipboardCopy,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
} from '@patternfly/react-core';

interface SecretRevealModalProps {
  isOpen: boolean;
  clientId: string;
  clientSecret: string;
  onClose: () => void;
}

const SecretRevealModal: React.FC<SecretRevealModalProps> = ({
  isOpen,
  clientId,
  clientSecret,
  onClose,
}) => {
  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      variant="medium"
      aria-label="Client secret"
    >
      <ModalHeader title={`Secret for ${clientId}`} />
      <ModalBody>
        <Alert
          variant="warning"
          isInline
          isPlain
          title="Copy this secret now — it will not be shown again."
          style={{ marginBottom: '1rem' }}
        />
        <ClipboardCopy isReadOnly hoverTip="Copy" clickTip="Copied" variant="expansion">
          {clientSecret}
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
