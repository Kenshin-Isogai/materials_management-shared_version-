interface GoogleCredentialResponse {
  credential?: string;
}

interface GoogleAccountsId {
  initialize(options: {
    client_id: string;
    callback: (response: GoogleCredentialResponse) => void;
  }): void;
  renderButton(
    parent: HTMLElement,
    options: {
      theme?: string;
      size?: string;
      shape?: string;
      text?: string;
      width?: number;
    },
  ): void;
}

interface Window {
  google?: {
    accounts?: {
      id: GoogleAccountsId;
    };
  };
}
