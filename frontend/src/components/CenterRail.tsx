import { useState, useEffect } from 'react';
import type { ThemeId } from '../lib/theme';

export type RailTab = 'overview' | 'objects' | 'areas' | 'details' | 'settings';

const RAIL_ITEMS: { id: RailTab; label: string; icon: string; title: string }[] = [
  { id: 'overview', label: 'OV', icon: '◎', title: 'Overview — briefing & situation' },
  { id: 'objects', label: 'OBJ', icon: '◆', title: 'Objects — entities & vessels' },
  { id: 'areas', label: 'AREA', icon: '▦', title: 'Areas — regions & zones' },
  { id: 'details', label: 'DET', icon: '☰', title: 'Details — selected entity' },
  { id: 'settings', label: 'SET', icon: '⚙', title: 'Settings — layers & config' },
];

export default function CenterRail({
  theme = 'cyber',
  activeTab = 'overview',
  onTabChange,
}: {
  theme?: ThemeId;
  activeTab?: RailTab;
  onTabChange?: (tab: RailTab) => void;
}) {
  const [internalTab, setInternalTab] = useState<RailTab>(activeTab);
  const tab = onTabChange ? activeTab : internalTab;

  useEffect(() => {
    if (onTabChange) return;
    setInternalTab(activeTab);
  }, [activeTab, onTabChange]);

  const handleSelect = (id: RailTab) => {
    if (onTabChange) {
      onTabChange(id);
    } else {
      setInternalTab(id);
    }
  };

  return (
    <nav
      className={`center-rail${theme === 'mss' ? ' center-rail--mss' : ''}`}
      role="tablist"
      aria-label="Center navigation rail"
    >
      {RAIL_ITEMS.map((item) => (
        <button
          key={item.id}
          role="tab"
          aria-selected={tab === item.id}
          className={`center-rail-btn${tab === item.id ? ' center-rail-btn--active' : ''}`}
          onClick={() => handleSelect(item.id)}
          title={item.title}
        >
          <span className="center-rail-icon">{item.icon}</span>
          <span className="center-rail-label">{item.label}</span>
        </button>
      ))}
    </nav>
  );
}
