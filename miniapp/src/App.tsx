import { useCallback, useEffect, useState } from 'react'
import {
  AppRoot,
  List,
  Section,
  Cell,
  Input,
  Image,
  Slider,
  Switch,
  Spinner,
} from '@telegram-apps/telegram-ui'

const tg = window.Telegram?.WebApp

interface Meta {
  video_id: string
  title: string
  duration: number
  thumbnail: string
}

const fmt = (s: number) => {
  const m = Math.floor(s / 60)
  const sec = Math.floor(s % 60)
  return `${m}:${sec.toString().padStart(2, '0')}`
}

const PasteIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2" />
    <rect x="8" y="2" width="8" height="4" rx="1" ry="1" />
  </svg>
)

const ClearIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="10" />
    <line x1="15" y1="9" x2="9" y2="15" />
    <line x1="9" y1="9" x2="15" y2="15" />
  </svg>
)

export default function App() {
  const [url, setUrl] = useState('')
  const [meta, setMeta] = useState<Meta | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [range, setRange] = useState<[number, number]>([0, 0])
  const [audio, setAudio] = useState(false)
  const [customTitle, setCustomTitle] = useState('')

  useEffect(() => {
    tg?.ready()
    tg?.expand()
  }, [])

  // Debounced metadata fetch on URL change
  useEffect(() => {
    const trimmed = url.trim()
    if (!trimmed) {
      setMeta(null)
      setError(null)
      return
    }
    setLoading(true)
    setError(null)
    const timer = setTimeout(async () => {
      try {
        const r = await fetch('/api/info', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url: trimmed }),
        })
        const data = await r.json()
        if (!r.ok) {
          setMeta(null)
          setError(data.error || 'Не удалось получить видео')
        } else {
          setMeta(data)
          setRange([0, data.duration])
        }
      } catch (e) {
        setMeta(null)
        setError('Сетевая ошибка')
      } finally {
        setLoading(false)
      }
    }, 500)
    return () => clearTimeout(timer)
  }, [url])

  const handlePaste = useCallback(async () => {
    const anyTg = tg as any
    if (anyTg?.readTextFromClipboard) {
      anyTg.readTextFromClipboard((text: string | null) => {
        if (text) setUrl(text)
      })
      return
    }
    try {
      const text = await navigator.clipboard.readText()
      if (text) setUrl(text)
    } catch {
      // clipboard unavailable
    }
  }, [])

  const onShare = useCallback(async () => {
    if (!meta || !tg) return
    tg.MainButton.showProgress()
    try {
      const start = Math.round(range[0])
      const end = Math.round(range[1])
      const r = await fetch('/api/share', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          init_data: tg.initData,
          video_id: meta.video_id,
          start,
          end: end >= meta.duration ? 0 : end,
          title: customTitle.trim() || meta.title,
          kind: audio ? 'audio' : 'video',
        }),
      })
      const data = await r.json()
      if (!r.ok || !data.prepared_message_id) {
        tg.showAlert(data.error || 'Не удалось подготовить сообщение')
        return
      }
      tg.shareMessage(data.prepared_message_id)
    } catch {
      tg.showAlert('Сетевая ошибка')
    } finally {
      tg.MainButton.hideProgress()
    }
  }, [meta, range, audio, customTitle])

  // MainButton wiring
  useEffect(() => {
    if (!tg?.MainButton) return
    tg.MainButton.setText('Поделиться')
    if (meta) {
      tg.MainButton.show()
      tg.MainButton.onClick(onShare)
      return () => tg.MainButton.offClick(onShare)
    } else {
      tg.MainButton.hide()
    }
  }, [meta, onShare])

  return (
    <AppRoot appearance={tg?.colorScheme}>
      <List>
        <Section header="YouTube ссылка">
          <Input
            placeholder="https://youtube.com/watch?v=..."
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            after={
              <button
                type="button"
                onClick={url ? () => setUrl('') : handlePaste}
                aria-label={url ? 'Очистить' : 'Вставить'}
                style={{
                  background: 'none',
                  border: 'none',
                  padding: 4,
                  margin: 0,
                  cursor: 'pointer',
                  color: 'var(--tgui--hint_color)',
                  display: 'flex',
                  alignItems: 'center',
                }}
              >
                {url ? <ClearIcon /> : <PasteIcon />}
              </button>
            }
          />
        </Section>

        {loading && (
          <Section>
            <Cell before={<Spinner size="s" />}>Загрузка...</Cell>
          </Section>
        )}

        {error && !loading && (
          <Section>
            <Cell multiline>{error}</Cell>
          </Section>
        )}

        {meta && !loading && (
          <>
            <Section header="Превью">
              <Cell
                before={<Image src={meta.thumbnail} size={48} />}
                multiline
                subtitle={`Длительность ${fmt(meta.duration)}`}
              >
                {meta.title}
              </Cell>
            </Section>

            <Section header={`Обрезка: ${fmt(range[0])} — ${fmt(range[1])}`}>
              <div style={{ padding: '16px 20px' }}>
                <Slider
                  multiple
                  min={0}
                  max={meta.duration}
                  step={1}
                  value={range}
                  onChange={(v) => setRange([Math.round(v[0]), Math.round(v[1])])}
                />
              </div>
            </Section>

            <Section header="Заголовок (необязательно)">
              <Input
                placeholder={meta.title}
                value={customTitle}
                onChange={(e) => setCustomTitle(e.target.value)}
              />
            </Section>

            <Section header="Режим">
              <Cell
                Component="label"
                after={
                  <Switch
                    checked={audio}
                    onChange={(e) => setAudio(e.target.checked)}
                  />
                }
              >
                Только аудио
              </Cell>
            </Section>
          </>
        )}
      </List>
    </AppRoot>
  )
}
