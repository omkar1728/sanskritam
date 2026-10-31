export interface AudioRef { job_id: number; meter_id: string; voice_id: string; steps: number; duration: number }
export interface VerseSource { work: string; reference: string; url?: string | null; edition?: string | null }
export interface Verse {
  id: string
  title: string | null
  text: string[]
  source: VerseSource
  notes: string | null
  meter_hint: string | null
  audio: AudioRef[]
  meanings?: Meanings
}
export interface NewVerse {
  id: string; title?: string | null; text: string[] | string; source: VerseSource
  notes?: string | null; meter_hint?: string | null
}
export interface Meter { id: string; name: string; syllable_count: number | null; sec_per_syll: number; is_prose: number | boolean }
export interface Voice { id: string; name: string; notice: string | null }
export type JobStatus = 'queued' | 'running' | 'aligning' | 'done' | 'failed' | 'cancelled'
export interface Job {
  id: number; verse_id: string; meter_id: string; voice_id: string
  executor: string; device: string; steps: number
  status: JobStatus; progress: number; log?: string | null; error: string | null
  created_at?: string
  asset?: { duration: number; aligned: number | boolean } | null
}
export interface Settings {
  executor: string; device: string; steps: string | number
  colab_drive_dir?: string; colab_timeout_s?: string | number
}
export interface SettingsUpdate {
  executor?: string; device?: string; steps?: number
  colab_drive_dir?: string; colab_timeout_s?: number
}
export interface ExecutorInfo { name: string; label: string; description: string }
export interface MeterSuggestion {
  meter_id: string; meter: string; syllables_per_segment: number | number[]; reason: string; exact: boolean
}
export interface AlignSyllable { slp1: string; start: number; end: number }
export interface AlignWord { text: string; slp1: string; start: number; end: number; syllables: AlignSyllable[] }
export interface Alignment { audio_duration: number; lines: { words: AlignWord[] }[] }
export interface CreateJob {
  verse_id: string; meter_id: string; voice_id?: string
  executor?: string; device?: string; steps?: number; seed?: number
}
export interface ExecutorHealth { [k: string]: unknown; ok?: boolean }
export type MeaningOrigin = 'seed' | 'user' | 'machine'
export interface WordMeaning {
  line: number; index: number; text: string; meaning: string; grammar: string | null
  origin: MeaningOrigin; reviewed: boolean
}
export interface MeaningSummary { translation: string; explanation: string | null; origin: MeaningOrigin; reviewed: boolean }
export interface Meanings { words: WordMeaning[]; summary: MeaningSummary | null }
export interface MeaningsUpdate {
  words: { line: number; index: number; text: string; meaning: string; grammar?: string | null }[]
  summary?: { translation: string; explanation?: string | null }
  origin?: MeaningOrigin; reviewed?: boolean
}
