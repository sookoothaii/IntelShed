import { useState } from 'react'

export type StepItem = {
  id: string
  label: string
  sublabel?: string
  status?: 'pending' | 'active' | 'done' | 'error'
  action?: { label: string; onClick: () => void }
}

export default function StepList({
  steps,
  onStepClick,
  className = '',
}: {
  steps: StepItem[]
  onStepClick?: (id: string) => void
  className?: string
}) {
  const [expandedId, setExpandedId] = useState<string | null>(null)

  return (
    <ol className={`step-list ${className}`.trim()}>
      {steps.map((step, i) => {
        const num = i + 1
        const isExpanded = expandedId === step.id
        const statusClass = step.status ? ` step-list-item--${step.status}` : ''
        return (
          <li
            key={step.id}
            className={`step-list-item${statusClass}`}
            onClick={() => {
              setExpandedId(isExpanded ? null : step.id)
              onStepClick?.(step.id)
            }}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                setExpandedId(isExpanded ? null : step.id)
                onStepClick?.(step.id)
              }
            }}
          >
            <div className="step-list-row">
              <span className="step-list-badge">{num}</span>
              <div className="step-list-content">
                <span className="step-list-label">{step.label}</span>
                {step.sublabel && (
                  <span className="step-list-sublabel">{step.sublabel}</span>
                )}
              </div>
              {step.action && (
                <button
                  className="step-list-action"
                  onClick={(e) => {
                    e.stopPropagation()
                    step.action!.onClick()
                  }}
                >
                  {step.action.label}
                </button>
              )}
            </div>
            {isExpanded && step.sublabel && (
              <div className="step-list-detail">{step.sublabel}</div>
            )}
          </li>
        )
      })}
    </ol>
  )
}
