import { usePosStore } from '@/stores/pos'
import { ProvisionalReceipt } from './ProvisionalReceipt'

/** The provisional receipt (and why it exists), shown in both modes of the till. */
export function ReceiptNotice({ storeName }: { storeName: string }) {
  const { receipt, droppedMidCheckout, dismiss } = usePosStore()
  if (!receipt) return null
  return (
    <>
      {droppedMidCheckout && (
        <p role="status" className="rounded-md bg-amber-50 p-3 text-sm text-amber-900">
          The connection dropped while completing this sale, so it was saved on this device. It will
          be sent automatically; nothing is lost and it cannot be booked twice.
        </p>
      )}
      <ProvisionalReceipt sale={receipt} storeName={storeName} onDismiss={dismiss} />
    </>
  )
}
