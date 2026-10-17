// /admin/activity: Active sessions, Auth events and Recent history, in that order.

"use client";

import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { AuthEventsSection } from "../AuthEventsSection";
import { RecentHistorySection } from "../RecentHistorySection";
import { SessionsSection } from "../SessionsSection";

export default function ActivityPage() {
  return (
    <>
      <AdminPageHeader title="Activity log">
        Who is signed in, who signed in, and what was played.
      </AdminPageHeader>
      <div className="space-y-7">
        <section aria-labelledby="activity-sessions">
          <h2 id="activity-sessions" className="title-2 text-ink">Active sessions</h2>
          <SessionsSection />
        </section>
        <section aria-labelledby="activity-auth-events">
          <h2 id="activity-auth-events" className="title-2 text-ink">Auth events</h2>
          <AuthEventsSection />
        </section>
        <section aria-labelledby="activity-history">
          <h2 id="activity-history" className="title-2 text-ink">Recent history</h2>
          <RecentHistorySection />
        </section>
      </div>
    </>
  );
}
