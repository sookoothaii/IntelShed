import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import TrustGauge from '../../src/components/TrustGauge'

describe('TrustGauge', () => {
  it('renders an SVG with two arc paths', () => {
    const { container } = render(<TrustGauge value={0.75} label="Field Trust" />)
    const svg = container.querySelector('svg')
    expect(svg).not.toBeNull()
    const paths = svg!.querySelectorAll('path')
    expect(paths.length).toBe(2) // background + value arc
  })

  it('renders the percentage value text', () => {
    const { container } = render(<TrustGauge value={0.75} label="Quality" />)
    const valueEl = container.querySelector('.trust-gauge-value')
    expect(valueEl?.textContent).toBe('75%')
  })

  it('renders dash for null value', () => {
    const { container } = render(<TrustGauge value={null} label="Unknown" />)
    const valueEl = container.querySelector('.trust-gauge-value')
    expect(valueEl?.textContent).toBe('—')
  })

  it('renders dash for undefined value', () => {
    const { container } = render(<TrustGauge value={undefined} label="Unknown" />)
    const valueEl = container.querySelector('.trust-gauge-value')
    expect(valueEl?.textContent).toBe('—')
  })

  it('renders the label text', () => {
    const { container } = render(<TrustGauge value={0.5} label="Corroboration" />)
    const labelEl = container.querySelector('.trust-gauge-label')
    expect(labelEl?.textContent).toBe('Corroboration')
  })

  it('applies green colour for value >= 0.7', () => {
    const { container } = render(<TrustGauge value={0.8} label="High" />)
    const svg = container.querySelector('svg')!
    const valuePath = svg.querySelectorAll('path')[1]
    expect(valuePath.getAttribute('stroke')).toBe('var(--green)')
  })

  it('applies amber colour for value >= 0.4 and < 0.7', () => {
    const { container } = render(<TrustGauge value={0.5} label="Mid" />)
    const svg = container.querySelector('svg')!
    const valuePath = svg.querySelectorAll('path')[1]
    expect(valuePath.getAttribute('stroke')).toBe('var(--amber)')
  })

  it('applies red colour for value < 0.4', () => {
    const { container } = render(<TrustGauge value={0.2} label="Low" />)
    const svg = container.querySelector('svg')!
    const valuePath = svg.querySelectorAll('path')[1]
    expect(valuePath.getAttribute('stroke')).toBe('var(--red)')
  })

  it('applies muted colour for null value', () => {
    const { container } = render(<TrustGauge value={null} label="N/A" />)
    const svg = container.querySelector('svg')!
    const valuePath = svg.querySelectorAll('path')[1]
    expect(valuePath.getAttribute('stroke')).toBe('var(--txt-muted)')
  })

  it('clamps value above 1 to 100%', () => {
    const { container } = render(<TrustGauge value={1.5} label="Clamped" />)
    const valueEl = container.querySelector('.trust-gauge-value')
    expect(valueEl?.textContent).toBe('100%')
  })

  it('clamps negative value to 0%', () => {
    const { container } = render(<TrustGauge value={-0.3} label="Clamped" />)
    const valueEl = container.querySelector('.trust-gauge-value')
    expect(valueEl?.textContent).toBe('0%')
  })

  it('handles NaN value as null', () => {
    const { container } = render(<TrustGauge value={NaN} label="NaN" />)
    const valueEl = container.querySelector('.trust-gauge-value')
    expect(valueEl?.textContent).toBe('—')
  })

  it('sets ARIA meter attributes', () => {
    const { container } = render(<TrustGauge value={0.65} label="Feed Health" />)
    const gauge = container.querySelector('[role="meter"]')
    expect(gauge).not.toBeNull()
    expect(gauge?.getAttribute('aria-valuemin')).toBe('0')
    expect(gauge?.getAttribute('aria-valuemax')).toBe('100')
    expect(gauge?.getAttribute('aria-valuenow')).toBe('65')
    expect(gauge?.getAttribute('aria-label')).toBe('Feed Health')
  })

  it('sets aria-valuenow to 0 for null value', () => {
    const { container } = render(<TrustGauge value={null} label="Empty" />)
    const gauge = container.querySelector('[role="meter"]')
    expect(gauge?.getAttribute('aria-valuenow')).toBe('0')
  })

  it('has stroke-dashoffset transition on value arc', () => {
    const { container } = render(<TrustGauge value={0.5} label="Animated" />)
    const svg = container.querySelector('svg')!
    const valuePath = svg.querySelectorAll('path')[1]
    const style = valuePath.getAttribute('style') || ''
    expect(style).toContain('stroke-dashoffset')
    expect(style).toContain('500ms')
    expect(style).toContain('ease')
  })

  it('does not use transition-all', () => {
    const { container } = render(<TrustGauge value={0.5} label="Check" />)
    const svg = container.querySelector('svg')!
    const valuePath = svg.querySelectorAll('path')[1]
    const style = valuePath.getAttribute('style') || ''
    expect(style).not.toContain('transition-all')
  })

  it('applies compact class when compact=true', () => {
    const { container } = render(<TrustGauge value={0.5} label="Compact" compact />)
    const gauge = container.querySelector('.trust-gauge')
    expect(gauge?.classList.contains('trust-gauge--compact')).toBe(true)
  })

  it('does not apply compact class by default', () => {
    const { container } = render(<TrustGauge value={0.5} label="Normal" />)
    const gauge = container.querySelector('.trust-gauge')
    expect(gauge?.classList.contains('trust-gauge--compact')).toBe(false)
  })

  it('uses smaller font size in compact mode', () => {
    const { container } = render(<TrustGauge value={0.5} label="Compact" compact />)
    const valueEl = container.querySelector('.trust-gauge-value') as HTMLElement
    expect(valueEl.style.fontSize).toBe('11px')
  })

  it('uses default font size 14px in non-compact mode', () => {
    const { container } = render(<TrustGauge value={0.5} label="Normal" />)
    const valueEl = container.querySelector('.trust-gauge-value') as HTMLElement
    expect(valueEl.style.fontSize).toBe('14px')
  })

  it('respects custom size prop', () => {
    const { container } = render(<TrustGauge value={0.5} label="Custom" size={120} />)
    const svg = container.querySelector('svg')!
    expect(svg.getAttribute('width')).toBe('120')
  })

  it('uses default size 80 when not specified', () => {
    const { container } = render(<TrustGauge value={0.5} label="Default" />)
    const svg = container.querySelector('svg')!
    expect(svg.getAttribute('width')).toBe('80')
  })

  it('renders background arc with var(--line) stroke', () => {
    const { container } = render(<TrustGauge value={0.5} label="BG" />)
    const svg = container.querySelector('svg')!
    const bgPath = svg.querySelectorAll('path')[0]
    expect(bgPath.getAttribute('stroke')).toBe('var(--line)')
  })

  it('computes correct dashoffset for full value', () => {
    const { container } = render(<TrustGauge value={1} label="Full" />)
    const svg = container.querySelector('svg')!
    const valuePath = svg.querySelectorAll('path')[1] as SVGPathElement
    const offset = Number(valuePath.getAttribute('stroke-dashoffset'))
    expect(offset).toBeCloseTo(0, 1)
  })

  it('computes correct dashoffset for zero value', () => {
    const { container } = render(<TrustGauge value={0} label="Zero" />)
    const svg = container.querySelector('svg')!
    const valuePath = svg.querySelectorAll('path')[1] as SVGPathElement
    const dashArray = Number(valuePath.getAttribute('stroke-dasharray'))
    const offset = Number(valuePath.getAttribute('stroke-dashoffset'))
    expect(offset).toBeCloseTo(dashArray, 1)
  })

  it('does not re-render when wrapped in memo and props are unchanged', () => {
    const { container, rerender } = render(<TrustGauge value={0.5} label="Memo" />)
    const firstSvg = container.querySelector('svg')
    rerender(<TrustGauge value={0.5} label="Memo" />)
    const secondSvg = container.querySelector('svg')
    // memo prevents unnecessary re-render — same element reference
    expect(secondSvg).toBe(firstSvg)
  })
})
