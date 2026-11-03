import type { AuctionStatus } from '../api'
import { STATUS_LABEL } from '../format'

export function StatusBadge({ status }: { status: AuctionStatus }) {
  return <span className={`badge badge-${status.toLowerCase()}`}>{STATUS_LABEL[status]}</span>
}
