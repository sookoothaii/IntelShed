import { useEffect, useRef, useState, useCallback } from 'react'
import { createPortal } from 'react-dom'
import type { ContextMenuAction } from '../lib/contextMenuActions'

type ContextMenuProps = {
  x: number
  y: number
  actions: ContextMenuAction[]
  onClose: () => void
}

export function ContextMenu({ x, y, actions, onClose }: ContextMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null)
  const [adjustedPos, setAdjustedPos] = useState({ x, y })

  useEffect(() => {
    const el = menuRef.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    let nx = x
    let ny = y
    if (x + rect.width > window.innerWidth - 8) nx = window.innerWidth - rect.width - 8
    if (y + rect.height > window.innerHeight - 8) ny = window.innerHeight - rect.height - 8
    if (nx < 8) nx = 8
    if (ny < 8) ny = 8
    setAdjustedPos({ x: nx, y: ny })
  }, [x, y])

  useEffect(() => {
    const el = menuRef.current?.querySelector<HTMLElement>('[role="menuitem"]:not([aria-disabled="true"])')
    el?.focus()
  }, [])

  useEffect(() => {
    const onPointerDown = (e: PointerEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        onClose()
      }
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        e.stopPropagation()
        onClose()
        return
      }
      if (e.key === 'ArrowDown' || e.key === 'Tab') {
        e.preventDefault()
        e.stopPropagation()
        const items = menuRef.current?.querySelectorAll<HTMLElement>('[role="menuitem"]:not([aria-disabled="true"])')
        if (!items || items.length === 0) return
        const arr = Array.from(items)
        const currentIdx = arr.findIndex((el) => el === document.activeElement)
        const next = currentIdx + 1 >= arr.length ? 0 : currentIdx + 1
        arr[next]?.focus()
        return
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        e.stopPropagation()
        const items = menuRef.current?.querySelectorAll<HTMLElement>('[role="menuitem"]:not([aria-disabled="true"])')
        if (!items || items.length === 0) return
        const arr = Array.from(items)
        const currentIdx = arr.findIndex((el) => el === document.activeElement)
        const next = currentIdx - 1 < 0 ? arr.length - 1 : currentIdx - 1
        arr[next]?.focus()
        return
      }
    }
    const onScroll = () => onClose()

    document.addEventListener('pointerdown', onPointerDown, true)
    document.addEventListener('keydown', onKey, true)
    window.addEventListener('scroll', onScroll, true)
    window.addEventListener('blur', onClose)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown, true)
      document.removeEventListener('keydown', onKey, true)
      window.removeEventListener('scroll', onScroll, true)
      window.removeEventListener('blur', onClose)
    }
  }, [onClose])

  const handleItemKey = useCallback(
    (e: React.KeyboardEvent, action: ContextMenuAction) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault()
        e.stopPropagation()
        if (!action.disabled) {
          action.handler()
          onClose()
        }
      }
    },
    [onClose],
  )

  if (actions.length === 0) return null

  return createPortal(
    <div
      ref={menuRef}
      role="menu"
      aria-orientation="vertical"
      className="ctx-menu"
      style={{
        position: 'fixed',
        left: adjustedPos.x,
        top: adjustedPos.y,
        zIndex: 10000,
      }}
    >
      {actions.map((action) => (
        <div key={action.id}>
          <div
            role="menuitem"
            tabIndex={action.disabled ? -1 : 0}
            aria-disabled={action.disabled ? 'true' : 'false'}
            className={`ctx-menu-item${action.disabled ? ' ctx-menu-item--disabled' : ''}`}
            onClick={() => {
              if (!action.disabled) {
                action.handler()
                onClose()
              }
            }}
            onKeyDown={(e) => handleItemKey(e, action)}
          >
            <span className="ctx-menu-icon" aria-hidden>{action.icon}</span>
            <span className="ctx-menu-label">{action.label}</span>
          </div>
          {action.separatorAfter && <div className="ctx-menu-separator" role="separator" />}
        </div>
      ))}
    </div>,
    document.body,
  )
}
