import React from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import {
  Code2,
  Search,
  GitBranch,
  Activity,
  Upload,
  Zap,
} from 'lucide-react';
import HealthIndicator from './HealthIndicator';

interface NavItemProps {
  to: string;
  icon: React.ReactNode;
  label: string;
  id: string;
}

const SidebarNavItem: React.FC<NavItemProps> = ({ to, icon, label, id }) => {
  const location = useLocation();
  const isActive = location.pathname === to;

  return (
    <NavLink
      to={to}
      id={id}
      className={`nav-item ${isActive ? 'active' : ''}`}
      aria-current={isActive ? 'page' : undefined}
    >
      {icon}
      {label}
    </NavLink>
  );
};

const Sidebar: React.FC = () => {
  return (
    <aside className="sidebar" aria-label="Main navigation">
      {/* Logo */}
      <div className="sidebar-logo">
        <Code2 size={26} />
        <div>
          <div className="sidebar-logo-text">CodeLens</div>
          <div className="sidebar-logo-sub">AI Code Intelligence</div>
        </div>
      </div>

      {/* Navigation */}
      <nav className="sidebar-nav">
        <span className="nav-section-label">Explore</span>

        <SidebarNavItem
          to="/"
          id="nav-search"
          icon={<Search size={16} />}
          label="Search"
        />

        <span className="nav-section-label">Manage</span>

        <SidebarNavItem
          to="/repositories"
          id="nav-repositories"
          icon={<GitBranch size={16} />}
          label="Repositories"
        />

        <SidebarNavItem
          to="/upload"
          id="nav-upload"
          icon={<Upload size={16} />}
          label="Upload ZIP"
        />

        <SidebarNavItem
          to="/jobs"
          id="nav-jobs"
          icon={<Activity size={16} />}
          label="Jobs"
        />

        <span className="nav-section-label">System</span>

        <SidebarNavItem
          to="/health"
          id="nav-health"
          icon={<Zap size={16} />}
          label="Health"
        />
      </nav>

      {/* Footer health dot */}
      <div className="sidebar-footer">
        <HealthIndicator compact />
      </div>
    </aside>
  );
};

export default Sidebar;
