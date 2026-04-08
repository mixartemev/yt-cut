interface TelegramWebApp {
  ready(): void
  expand(): void
  initData: string
  colorScheme: 'light' | 'dark'
  showAlert(message: string, callback?: () => void): void
  shareMessage(msgId: string, callback?: (success: boolean) => void): void
  MainButton: {
    text: string
    isVisible: boolean
    setText(text: string): void
    show(): void
    hide(): void
    enable(): void
    disable(): void
    showProgress(leaveActive?: boolean): void
    hideProgress(): void
    onClick(handler: () => void): void
    offClick(handler: () => void): void
  }
}

interface Window {
  Telegram?: { WebApp: TelegramWebApp }
}
