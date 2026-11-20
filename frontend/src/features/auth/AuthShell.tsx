import type { ReactNode } from 'react'

const FEATURES = ['⚡ Fast billing', '▣ Smart inventory', '↗ Business insights']

/**
 * The split sign-in layout from the approved prototype (docs/ui/wearstack_prototype_login.html):
 * a navy brand panel on the left, the form on the right. On phones only the form is shown.
 */
export function AuthShell({ children, wide }: { children: ReactNode; wide?: boolean }) {
  return (
    <div className="grid min-h-screen bg-ws-bg md:grid-cols-[1.05fr_.95fr]">
      <section className="relative hidden flex-col justify-between overflow-hidden bg-gradient-to-br from-[#124b9b] to-[#0d3470] p-[clamp(25px,5vw,70px)] text-white md:flex">
        <div
          aria-hidden
          className="absolute -top-[130px] -right-[180px] size-[440px] rounded-full bg-ws-blue opacity-[.18]"
        />
        <div
          aria-hidden
          className="absolute -bottom-[160px] -left-[120px] size-[320px] rounded-full bg-ws-orange opacity-[.18]"
        />
        <div className="relative z-10 flex items-center gap-3">
          <div
            aria-hidden
            className="grid size-12 place-items-center rounded-[13px] bg-ws-orange text-2xl"
          >
            👕
          </div>
          <div>
            <div className="text-[25px] font-extrabold tracking-[-1px]">
              wearstack<span className="text-[#ffb36f]">.</span>
            </div>
            <div className="text-[10px] tracking-[1px] text-[#cfe0fa]">RETAIL MANAGEMENT</div>
          </div>
        </div>
        <div className="relative z-10 max-w-[540px]">
          <h1 className="mb-[18px] text-[clamp(34px,4.4vw,64px)] leading-[1.06] font-bold tracking-[-2px]">
            Your store.
            <br />
            <em className="text-[#ff9a50] not-italic">Your style.</em>
          </h1>
          <p className="max-w-[420px] text-base leading-[1.7] text-[#d7e7ff]">
            Spend less time managing stock and billing. Spend more time growing the business you
            love.
          </p>
          <div className="mt-[26px] flex flex-wrap gap-2.5">
            {FEATURES.map((f) => (
              <span
                key={f}
                className="rounded-full border border-white/[.19] bg-white/[.07] px-[13px] py-[9px] text-xs text-[#e4efff]"
              >
                {f}
              </span>
            ))}
          </div>
        </div>
        <div className="relative z-10 text-[11px] tracking-[1px] text-[#b8d0ef]">
          BUILT FOR THE WAY YOU RETAIL.
        </div>
      </section>
      <section className="flex items-center justify-center bg-white p-[22px] md:p-7">
        <div className={`w-full ${wide ? 'max-w-xl' : 'max-w-[420px]'}`}>{children}</div>
      </section>
    </div>
  )
}
