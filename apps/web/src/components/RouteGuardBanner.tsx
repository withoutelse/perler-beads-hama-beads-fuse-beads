export function RouteGuardBanner() {
  return (
    <div className="route-guard" role="status">
      <div className="route-guard-icon">✓</div>
      <div className="route-guard-copy">
        <strong>路线守卫已锁定</strong>
        <p>按造型分件 + 双面有孔 + 免胶拼插。水平实心切片、胶水和连接棒会被拒绝。</p>
      </div>
      <span className="route-guard-tag">ROUTE LOCKED</span>
    </div>
  );
}
