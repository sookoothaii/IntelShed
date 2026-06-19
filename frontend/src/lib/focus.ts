export type WebcamFocusRef = {
  id: string
  name?: string
  source?: string
  url?: string
  embed?: string | null
  detail_url?: string
  category?: string
  country?: string
}

export type FocusTarget = {
  ts: number
  kind: string
  lon: number
  lat: number
  height?: number
  title: string
  lines: string[]
  link?: string
  webcam?: WebcamFocusRef
}
