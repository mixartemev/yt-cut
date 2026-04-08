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

export default function App() {
  const [url, setUrl] = useState('')
  const [meta, setMeta] = useState<Meta | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [range, setRange] = useState<[number, number]>([0, 0])
  const [audio, setAudio] = useState(false)

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

  const onShare = useCallback(async () => {
    if (!meta || !tg) return
    tg.MainButton.showProgress()
    try {
      const r = await fetch('/api/share', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          init_data: tg.initData,
          video_id: meta.video_id,
          start: range[0],
          end: range[1] >= meta.duration ? 0 : range[1],
          title: meta.title,
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
  }, [meta, range, audio])

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
                  onChange={(v) => setRange(v)}
                />
              </div>
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
