import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { Alignment } from '../types'
import { findSyllableIndex, findWordIndex, flattenWords, formatTime } from './helpers'
import './player.css'

const PAD = 0.05
const PRESETS = [0.5, 0.75, 1, 1.25]

interface Clip { start: number; end: number }

export default function Player({ src, alignment }: { src: string; alignment: Alignment }) {
  const audioRef = useRef<HTMLAudioElement>(null)
  const words = useMemo(() => flattenWords(alignment), [alignment])
  const [wordIdx, setWordIdx] = useState(-1)
  const [sylIdx, setSylIdx] = useState(-1)
  const [playing, setPlaying] = useState(false)
  const [time, setTime] = useState(0)
  const [duration, setDuration] = useState(alignment.audio_duration)
  const [rate, setRate] = useState(1)
  const [loopClip, setLoopClip] = useState(false)
  const [lineLoop, setLineLoop] = useState(false)

  const clipRef = useRef<Clip | null>(null)
  const lastClipRef = useRef<Clip | null>(null)
  const loopClipRef = useRef(false)
  const lineRef = useRef<Clip | null>(null)
  const wordIdxRef = useRef(-1)

  useEffect(() => { loopClipRef.current = loopClip }, [loopClip])

  const applyRate = useCallback(() => {
    const a = audioRef.current
    if (!a) return
    a.playbackRate = rate
    const x = a as HTMLAudioElement & { webkitPreservesPitch?: boolean; mozPreservesPitch?: boolean }
    a.preservesPitch = true
    x.webkitPreservesPitch = true
    x.mozPreservesPitch = true
  }, [rate])
  useEffect(applyRate, [applyRate])

  // Stop / loop checks, shared by rAF and timeupdate.
  const check = useCallback(() => {
    const a = audioRef.current
    if (!a) return
    const t = a.currentTime
    const clip = clipRef.current
    if (clip && t >= clip.end) {
      if (loopClipRef.current) a.currentTime = clip.start
      else { a.pause(); clipRef.current = null }
    } else if (!clip && lineRef.current && t >= lineRef.current.end) {
      a.currentTime = lineRef.current.start
    }
  }, [])

  useEffect(() => {
    let raf = 0
    const tick = () => {
      check()
      const a = audioRef.current
      if (a) {
        const t = a.currentTime
        setTime(t)
        const wi = findWordIndex(words.map(w => w.word), t)
        wordIdxRef.current = wi >= 0 ? wi : wordIdxRef.current
        setWordIdx(wi)
        setSylIdx(wi >= 0 ? findSyllableIndex(words[wi].word.syllables, t) : -1)
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [words, check])

  const playClip = useCallback((start: number, end: number) => {
    const a = audioRef.current
    if (!a) return
    const c = { start: Math.max(0, start - PAD), end: end + PAD }
    clipRef.current = c
    lastClipRef.current = c
    a.currentTime = c.start
    applyRate()
    void a.play().catch(() => { clipRef.current = null })
  }, [applyRate])

  const playFull = useCallback(() => {
    const a = audioRef.current
    if (!a) return
    if (!a.paused) { a.pause(); return }
    if (!clipRef.current && a.ended) a.currentTime = 0
    applyRate()
    void a.play()
  }, [applyRate])

  const seek = (t: number) => {
    const a = audioRef.current
    if (!a) return
    clipRef.current = null
    a.currentTime = t
    setTime(t)
  }

  const toggleLineLoop = useCallback(() => {
    if (lineRef.current) { lineRef.current = null; setLineLoop(false); return }
    const w = words[wordIdxRef.current >= 0 ? wordIdxRef.current : 0]
    if (!w) return
    const lw = words.filter(x => x.line === w.line)
    lineRef.current = { start: lw[0].word.start, end: lw[lw.length - 1].word.end + PAD }
    clipRef.current = null
    setLineLoop(true)
    const a = audioRef.current
    if (a) { a.currentTime = lineRef.current.start; void a.play() }
  }, [words])

  const step = useCallback((d: number) => {
    const cur = wordIdxRef.current
    const i = Math.min(words.length - 1, Math.max(0, cur + d))
    const w = words[i]
    if (w) { wordIdxRef.current = i; playClip(w.word.start, w.word.end) }
  }, [words, playClip])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null
      if (el && (/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) && (el as HTMLInputElement).type !== 'range' || el.isContentEditable)) return
      if (e.ctrlKey || e.metaKey || e.altKey) return
      if (e.key === ' ') { e.preventDefault(); playFull() }
      else if (e.key === 'ArrowLeft') { e.preventDefault(); step(-1) }
      else if (e.key === 'ArrowRight') { e.preventDefault(); step(1) }
      else if (e.key === 'r' || e.key === 'R') {
        const c = lastClipRef.current
        if (c) playClip(c.start + PAD, c.end - PAD)
        else toggleLineLoop()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [playFull, step, playClip, toggleLineLoop])

  const spanProps = (s: number, e: number) => ({ 'data-start': s, 'data-end': e })

  return (
    <div className="player">
      <audio ref={audioRef} src={src} preload="auto"
        onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} onEnded={() => setPlaying(false)}
        onLoadedMetadata={e => { setDuration(e.currentTarget.duration); applyRate() }}
        onTimeUpdate={check} />
      <div className="card">
        <div className="verse devanagari">
          {alignment.lines.map((_, li) => (
            <div className="vline" key={li}>
              {words.filter(w => w.line === li).map(w => (
                <span key={w.index} className={'w' + (w.index === wordIdx ? ' cur' : '')}
                  {...spanProps(w.word.start, w.word.end)}
                  onClick={() => playClip(w.word.start, w.word.end)}>
                  {w.pieces
                    ? w.pieces.map((p, si) => {
                      const sy = w.word.syllables[si]
                      return (
                        <span key={si} className={'s' + (w.index === wordIdx && si === sylIdx ? ' cur' : '')}
                          {...spanProps(sy.start, sy.end)}
                          onClick={e => { e.stopPropagation(); playClip(sy.start, sy.end) }}>{p}</span>
                      )
                    })
                    : w.word.text}
                </span>
              ))}
            </div>
          ))}
        </div>
      </div>
      <div className="card">
        <div className="controls">
          <button className="btn" onClick={playFull}>{playing ? 'Pause' : 'Play'}</button>
          <input className="seek" type="range" min={0} max={duration || 0} step={0.01} value={Math.min(time, duration || 0)}
            aria-label="Seek" onChange={e => seek(Number(e.target.value))} />
          <span className="time">{formatTime(time)} / {formatTime(duration)}</span>
          <button className={'btn secondary' + (loopClip ? ' on' : '')} aria-pressed={loopClip}
            onClick={() => setLoopClip(v => !v)}>Loop this</button>
          <button className={'btn secondary' + (lineLoop ? ' on' : '')} aria-pressed={lineLoop}
            onClick={toggleLineLoop}>Repeat line</button>
        </div>
        <div className="speed">
          <span className="muted">Speed</span>
          <input type="range" min={0.5} max={1.5} step={0.05} value={rate} aria-label="Speed"
            onChange={e => setRate(Number(e.target.value))} />
          <span>{rate.toFixed(2)}x</span>
          {PRESETS.map(p => (
            <button key={p} className={'btn secondary' + (rate === p ? ' on' : '')} onClick={() => setRate(p)}>{p}x</button>
          ))}
        </div>
        <div className="kbd">Space play/pause, Left/Right previous/next word, R repeat last clip or line. Click a word or syllable to hear it.</div>
      </div>
    </div>
  )
}
