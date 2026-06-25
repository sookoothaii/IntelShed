import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import Sparkline from '../../src/components/Sparkline'

describe('Sparkline', () => {
  it('renders placeholder line for < 2 data points', () => {
    const { container } = render(<Sparkline data={[42]} />)
    const svg = container.querySelector('svg')
    expect(svg).not.toBeNull()
    const line = svg!.querySelector('line')
    expect(line).not.toBeNull()
  })

  it('renders placeholder for empty data', () => {
    const { container } = render(<Sparkline data={[]} />)
    const svg = container.querySelector('svg')
    expect(svg).not.toBeNull()
  })

  it('renders full sparkline for valid series', () => {
    const { container } = render(<Sparkline data={[1, 2, 3, 4, 5]} />)
    const svg = container.querySelector('svg')
    expect(svg).not.toBeNull()
    const paths = svg!.querySelectorAll('path')
    expect(paths.length).toBeGreaterThanOrEqual(2) // area + line
    const circle = svg!.querySelector('circle')
    expect(circle).not.toBeNull()
  })

  it('uses green stroke for upward series by default', () => {
    const { container } = render(<Sparkline data={[1, 2, 3]} />)
    const svg = container.querySelector('svg')!
    const paths = svg.querySelectorAll('path')
    const line = Array.from(paths).find((p: Element) => p.getAttribute('stroke') !== 'none')
    expect(line?.getAttribute('stroke')).toBe('#00e5a0')
  })

  it('uses red stroke for downward series by default', () => {
    const { container } = render(<Sparkline data={[5, 3, 1]} />)
    const svg = container.querySelector('svg')!
    const paths = svg.querySelectorAll('path')
    const line = Array.from(paths).find((p: Element) => p.getAttribute('stroke') !== 'none')
    expect(line?.getAttribute('stroke')).toBe('#ff4d5e')
  })

  it('uses explicit stroke when provided', () => {
    const { container } = render(<Sparkline data={[1, 2, 3]} stroke="#ff00ff" />)
    const svg = container.querySelector('svg')!
    const paths = svg.querySelectorAll('path')
    const line = Array.from(paths).find((p: Element) => p.getAttribute('stroke') !== 'none')
    expect(line?.getAttribute('stroke')).toBe('#ff00ff')
  })

  it('renders without fill when fill=false', () => {
    const { container } = render(<Sparkline data={[1, 2, 3]} fill={false} />)
    const svg = container.querySelector('svg')
    // area path starts with M0 {height}, line path starts with M0.something
    const paths = svg!.querySelectorAll('path')
    const areaPath = Array.from(paths).find((p: Element) => p.getAttribute('fill')?.startsWith('url('))
    expect(areaPath).toBeUndefined()
  })

  it('renders without baseline when baseline=false', () => {
    const { container } = render(<Sparkline data={[1, 2, 3]} baseline={false} />)
    const svg = container.querySelector('svg')
    const dashes = svg!.querySelectorAll('line[stroke-dasharray]')
    expect(dashes.length).toBe(0)
  })

  it('filters non-finite values', () => {
    const { container } = render(<Sparkline data={[1, NaN, 3, Infinity, 5]} />)
    const svg = container.querySelector('svg')
    const circle = svg!.querySelector('circle')
    expect(circle).not.toBeNull()
  })
})
