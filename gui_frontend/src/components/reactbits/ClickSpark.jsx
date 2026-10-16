import React from 'react';

export default function ClickSpark({
  children,
  sparkColor: _sparkColor,
  sparkSize: _sparkSize,
  sparkCount: _sparkCount,
  duration: _duration,
  className = '',
  onClick,
  disabled = false,
  ...props
}) {
  const handleClick = (e) => {
    if (disabled) return;
    if (onClick) onClick(e);
  };

  return (
    <div
      onClick={handleClick}
      className={`relative inline-block w-full ${className}`}
      {...props}
    >
      {children}
    </div>
  );
}
