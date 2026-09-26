import './globals.css';
import React from 'react';

export const metadata = {
  title: 'Autonomous Support & Action Portal',
  description: 'LangGraph Autonomous Customer Support with HITL Approval Gateways',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
