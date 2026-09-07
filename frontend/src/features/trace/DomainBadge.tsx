/**
 * 域名色块——首字母 + 域名哈希出的稳定色块，不发任何远程请求（ADR-0028）。
 *
 * 公开站上给每个搜索结果发一个 favicon 请求，等于把访客看了什么泄露给
 * 第三方域名；这是隐私取舍，不是美术选择。
 */

const PALETTE = ["#d8f36a", "#e7b58d", "#8d9690", "#6ac3f3", "#f38ba0", "#c6a0f3"];

function hashDomain(domain: string): number {
  let hash = 0;
  for (let i = 0; i < domain.length; i += 1) {
    hash = (hash * 31 + domain.charCodeAt(i)) >>> 0;
  }
  return hash;
}

export function domainOf(url: string): string | null {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return null;
  }
}

interface DomainBadgeProps {
  domain: string;
}

export function DomainBadge({ domain }: DomainBadgeProps) {
  const color = PALETTE[hashDomain(domain) % PALETTE.length];
  return (
    <span className="domain-badge" style={{ background: color }} aria-hidden="true">
      {domain.charAt(0).toUpperCase()}
    </span>
  );
}
