import React, { useEffect, useState } from "react";
import api from "../lib/api";
import {
  Building2, Phone, Mail, MapPin, ShieldCheck, ShieldAlert, Star,
  BedDouble, Stethoscope, Ambulance, FlaskConical, Award, Clock,
  Wallet, CheckCircle2, XCircle, ExternalLink,
} from "lucide-react";
import { Avatar } from "./Contacts";
import { fmtCurrency, relativeTime } from "../lib/constants";

// Profile page — full-parity with the mobile Provider App profile screen.
// Reads /api/provider/me which now returns { contact, user, profile }
// where `profile` is the vertical-specific Supabase row.

const T = {
  card: "bg-white border border-[#DFE1E6] rounded-md",
  sectionHead: "px-4 py-2 text-[10px] uppercase tracking-wider text-[#5E6C84] font-semibold border-b border-[#DFE1E6] bg-[#F8F9FA]",
};

function Row({ label, value, mono = false }) {
  if (value === null || value === undefined || value === "") return null;
  return (
    <div className="py-2 flex items-baseline gap-3 border-b border-[#F1F2F4] last:border-0">
      <div className="text-[11px] uppercase tracking-wider text-[#5E6C84] w-40 shrink-0">{label}</div>
      <div className={`text-sm text-[#091E42] flex-1 min-w-0 ${mono ? "font-mono" : ""}`}>{value}</div>
    </div>
  );
}

function Chip({ children, tone = "neutral" }) {
  const map = {
    neutral: "bg-[#F4F5F7] text-[#42526E]",
    good: "bg-[#E3FCEF] text-[#006644]",
    warn: "bg-[#FFFAE6] text-[#974F0C]",
    danger: "bg-[#FFEBE6] text-[#BF2600]",
    info: "bg-[#DEEBFF] text-[#0747A6]",
  };
  return <span className={`inline-flex items-center px-2 py-0.5 text-[10px] font-bold rounded-full ${map[tone]}`}>{children}</span>;
}

function BoolRow({ label, value }) {
  if (value === null || value === undefined) return null;
  return <Row label={label} value={value ? <Chip tone="good"><CheckCircle2 className="h-3 w-3 mr-1" /> Yes</Chip> : <Chip tone="danger"><XCircle className="h-3 w-3 mr-1" /> No</Chip>} />;
}

const listify = (v) => {
  if (!v) return null;
  if (Array.isArray(v)) return v.length ? v.join(" · ") : null;
  if (typeof v === "object") return Object.keys(v).join(" · ");
  return String(v);
};

export default function ProviderProfile() {
  const [data, setData] = useState(null);
  useEffect(() => { (async () => setData((await api.get("/provider/me")).data))(); }, []);

  if (!data) return <div className="p-8 text-sm text-[#5E6C84]" data-testid="provider-profile-loading">Loading…</div>;
  const c = data.contact || {};
  const u = data.user || {};
  const p = data.profile || {};
  const vertical = u.provider_type;

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6 max-w-5xl" data-testid="provider-profile-page">
      <div>
        <div className="overline flex items-center gap-1"><Building2 className="h-3 w-3" /> Your Account</div>
        <h1 className="font-heading text-2xl sm:text-3xl font-black tracking-tight text-[#091E42] mt-1">Profile</h1>
        <p className="text-sm text-[#5E6C84] mt-1">Live view of what the Trata Provider App shows for your account. Manage KYC docs on the <a href="/provider/kyc" className="text-[#0052CC] font-semibold hover:underline">KYC tab</a>.</p>
      </div>

      {/* ── Header card ─────────────────────────────────────────────── */}
      <div className={T.card + " p-6"}>
        <div className="flex flex-wrap items-start gap-6">
          <Avatar name={p.name || p.full_name || p.business_name || c.name} src={p.profile_image || p.logo_url || p.photo_url || c.avatar} size={72} />
          <div className="flex-1 min-w-0">
            <div className="overline flex items-center gap-2">
              {(vertical || "").toUpperCase()}
              {p.hospital_type && <Chip tone="info">{p.hospital_type}</Chip>}
              {p.doctor_type && <Chip tone="info">{p.doctor_type}</Chip>}
              {p.status && <Chip tone={p.status === "approved" ? "good" : p.status === "rejected" ? "danger" : "warn"}>{p.status.toUpperCase()}</Chip>}
              {p.verification_status && <Chip tone={p.verification_status === "verified" || p.verification_status === "approved" ? "good" : "warn"}>{p.verification_status.toUpperCase()}</Chip>}
              {p.availability === true && <Chip tone="good">AVAILABLE</Chip>}
              {p.is_on_duty === true && <Chip tone="good">ON DUTY</Chip>}
              {p.is_active === false && <Chip tone="danger">INACTIVE</Chip>}
            </div>
            <h2 className="font-heading text-2xl font-black tracking-tight text-[#091E42] mt-1">
              {p.name || p.full_name || p.business_name || p.lab_name || c.name}
            </h2>
            {p.short_tagline && <div className="text-sm text-[#42526E] mt-1">{p.short_tagline}</div>}
            {p.description && <div className="text-sm text-[#42526E] mt-2 line-clamp-3">{p.description}</div>}
            <div className="flex flex-wrap items-center gap-4 mt-3 text-sm text-[#5E6C84]">
              {(p.phone || c.phone) && <span className="inline-flex items-center gap-1.5"><Phone className="h-3.5 w-3.5" /> +91 {p.phone || c.phone}</span>}
              {(p.email || c.email) && <span className="inline-flex items-center gap-1.5"><Mail className="h-3.5 w-3.5" /> {p.email || c.email}</span>}
              {(p.city || c.city) && <span className="inline-flex items-center gap-1.5"><MapPin className="h-3.5 w-3.5" /> {p.city || c.city}{(p.state || c.state) ? `, ${p.state || c.state}` : ""}</span>}
              {(p.average_rating || p.avg_rating || p.rating) && <span className="inline-flex items-center gap-1.5 text-[#FFAB00]"><Star className="h-3.5 w-3.5 fill-current" /> {(p.average_rating || p.avg_rating || p.rating).toFixed(1)} {p.review_count || p.total_reviews ? `· ${p.review_count || p.total_reviews} reviews` : ""}</span>}
            </div>
          </div>
          <div className="shrink-0">
            {c.is_verified ? (
              <a href="/provider/kyc" className="inline-flex items-center gap-2 px-3 py-2 bg-[#E3FCEF] text-[#006644] rounded-md text-sm font-semibold hover:bg-[#ABF5D1]" data-testid="kyc-status-verified">
                <ShieldCheck className="h-4 w-4" /> KYC Verified
              </a>
            ) : (
              <a href="/provider/kyc" className="inline-flex items-center gap-2 px-3 py-2 bg-[#FFFAE6] text-[#974F0C] rounded-md text-sm font-semibold hover:bg-[#FFF0B3]" data-testid="kyc-status-pending">
                <ShieldAlert className="h-4 w-4" /> Complete KYC →
              </a>
            )}
          </div>
        </div>
      </div>

      {/* ── Contact & registration ──────────────────────────────────── */}
      <section className={T.card} data-testid="profile-contact-section">
        <div className={T.sectionHead}>Contact & registration</div>
        <div className="p-4">
          <Row label="Business phone" value={p.phone ? `+91 ${p.phone}` : null} mono />
          <Row label="Alternate phone" value={p.alternate_phone ? `+91 ${p.alternate_phone}` : null} mono />
          <Row label="Email" value={p.email} />
          <Row label="Website" value={p.website ? <a href={p.website} target="_blank" rel="noreferrer" className="text-[#0052CC] hover:underline inline-flex items-center gap-1">{p.website} <ExternalLink className="h-3 w-3" /></a> : null} />
          <Row label="Address" value={p.address} />
          <Row label="City / State" value={[p.city, p.state, p.pincode].filter(Boolean).join(" · ")} />
          <Row label="License #" value={p.license_number} mono />
          <Row label="Registration #" value={p.registration_number} mono />
          <Row label="GST #" value={p.gst_number} mono />
          <Row label="HFR ID" value={p.hfr_id ? <>{p.hfr_id} {p.hfr_verified && <Chip tone="good">VERIFIED</Chip>}</> : null} mono />
          <Row label="HPR ID" value={p.hpr_id ? <>{p.hpr_id} {p.hpr_verified && <Chip tone="good">VERIFIED</Chip>}</> : null} mono />
          <Row label="Referral code" value={p.referral_code} mono />
          <Row label="Onboarded by" value={p.onboarded_by || c.assigned_agent_name} />
          {p.created_at && <Row label="Joined" value={`${relativeTime(p.created_at)}`} />}
        </div>
      </section>

      {/* ── Vertical-specific detail ────────────────────────────────── */}
      {vertical === "hospital" && <HospitalDetail p={p} />}
      {vertical === "ambulance" && <AmbulanceDetail p={p} />}
      {vertical === "doctor" && <DoctorDetail p={p} />}
      {vertical === "pathology" && <PathologyDetail p={p} />}

      {/* ── CRM meta ────────────────────────────────────────────────── */}
      <section className={T.card} data-testid="profile-crm-meta">
        <div className={T.sectionHead}>Trata Admin Console tracking</div>
        <div className="p-4">
          <Row label="Pipeline stage" value={c.pipeline_stage} />
          <Row label="Deal value" value={c.deal_value ? fmtCurrency(c.deal_value) : null} />
          <Row label="Assigned agent" value={c.assigned_agent_name} />
          <Row label="KYC status" value={c.kyc_status} />
          <Row label="Source" value={c.source} />
        </div>
      </section>

      {!data.profile && u.provider_type && (
        <div className="text-xs text-[#5E6C84] p-4 bg-[#F4F5F7] rounded-md" data-testid="profile-no-supabase-row">
          No vertical profile row yet in the shared TrataHealth backend. Complete the setup on the mobile Provider App to populate the rest of this screen.
        </div>
      )}
    </div>
  );
}

// ── vertical-specific detail cards ──────────────────────────────────────────
function HospitalDetail({ p }) {
  const beds = p.available_beds_by_type || {};
  const flags = p.facility_flags || {};
  return (
    <>
      <section className={T.card} data-testid="profile-hospital-facility">
        <div className={T.sectionHead}><BedDouble className="h-3 w-3 inline mr-1" /> Facility</div>
        <div className="p-4">
          <Row label="Total capacity" value={p.capacity} />
          {Object.keys(beds).length > 0 && (
            <Row label="Beds by type" value={Object.entries(beds).map(([k, v]) => `${k}: ${v}`).join(" · ")} mono />
          )}
          <BoolRow label="24×7 ER" value={p.has_24x7_er} />
          <BoolRow label="Emergency services" value={p.has_emergency_services} />
          <Row label="Top services" value={listify(p.top_services)} />
          <Row label="Specializations" value={listify(p.specializations) || p.specialization} />
          {Object.keys(flags).length > 0 && <Row label="Facility flags" value={Object.entries(flags).filter(([, v]) => v).map(([k]) => k).join(" · ") || "—"} />}
          <Row label="Opening hours" value={typeof p.opening_hours === "string" ? p.opening_hours : listify(p.opening_hours)} />
        </div>
      </section>
    </>
  );
}

function AmbulanceDetail({ p }) {
  return (
    <>
      <section className={T.card} data-testid="profile-ambulance-fleet">
        <div className={T.sectionHead}><Ambulance className="h-3 w-3 inline mr-1" /> Fleet & service area</div>
        <div className="p-4">
          <Row label="Owner" value={p.owner_name} />
          <Row label="Total ambulances" value={p.total_ambulances} />
          <Row label="Service radius" value={p.service_radius_km ? `${p.service_radius_km} km` : null} />
          <Row label="Service zones" value={listify(p.service_zones) || listify(p.service_areas)} />
          <BoolRow label="Available" value={p.availability} />
          <Row label="Total bookings" value={p.total_bookings} />
          <Row label="Completed" value={p.completed_bookings} />
          <Row label="Average rating" value={p.average_rating ? `${p.average_rating.toFixed(1)} ★` : null} />
          <Row label="Lifetime earnings" value={p.total_earnings ? fmtCurrency(p.total_earnings) : null} />
        </div>
      </section>
      <section className={T.card} data-testid="profile-ambulance-rates">
        <div className={T.sectionHead}><Wallet className="h-3 w-3 inline mr-1" /> Rates</div>
        <div className="p-4">
          <Row label="Non-emergency base" value={p.non_emergency_base_fare ? fmtCurrency(p.non_emergency_base_fare) : null} />
          <Row label="Non-emergency per km" value={p.non_emergency_per_km_rate ? fmtCurrency(p.non_emergency_per_km_rate) : null} />
          <Row label="Mortuary base" value={p.mortuary_base_fare ? fmtCurrency(p.mortuary_base_fare) : null} />
          <Row label="Mortuary per km" value={p.mortuary_per_km_rate ? fmtCurrency(p.mortuary_per_km_rate) : null} />
        </div>
      </section>
    </>
  );
}

function DoctorDetail({ p }) {
  return (
    <>
      <section className={T.card} data-testid="profile-doctor-clinical">
        <div className={T.sectionHead}><Stethoscope className="h-3 w-3 inline mr-1" /> Clinical profile</div>
        <div className="p-4">
          <Row label="Specialization" value={listify(p.specialization) || p.other_specialization} />
          <Row label="Qualification" value={listify(p.qualification) || p.other_qualification} />
          <Row label="Experience" value={p.experience ? `${p.experience} years` : null} />
          <Row label="Doctor type" value={p.doctor_type} />
          <Row label="Hospital / Clinic" value={p.hospital_name || p.clinic_name || p.facility_name} />
          <BoolRow label="Video consultation" value={p.accepts_video_consultation} />
          <BoolRow label="In-person consultation" value={p.accepts_in_person_consultation} />
          <Row label="MoC empanelled" value={p.is_moc_empanelled ? <Chip tone="good">Yes · {listify(p.moc_specialties) || ""}</Chip> : null} />
          <Row label="Consultation duration" value={p.consultation_duration ? `${p.consultation_duration} min` : null} />
        </div>
      </section>
      <section className={T.card} data-testid="profile-doctor-fees">
        <div className={T.sectionHead}><Wallet className="h-3 w-3 inline mr-1" /> Consultation fees</div>
        <div className="p-4">
          <Row label="Video consultation" value={p.video_consultation_fee ? fmtCurrency(p.video_consultation_fee) : null} />
          <Row label="In-person consultation" value={p.in_person_consultation_fee ? fmtCurrency(p.in_person_consultation_fee) : null} />
          <Row label="Follow-up" value={p.follow_up_consultation_fee ? fmtCurrency(p.follow_up_consultation_fee) : null} />
          <Row label="Emergency" value={p.emergency_consultation_fee ? fmtCurrency(p.emergency_consultation_fee) : null} />
        </div>
      </section>
    </>
  );
}

function PathologyDetail({ p }) {
  return (
    <>
      <section className={T.card} data-testid="profile-pathology-lab">
        <div className={T.sectionHead}><FlaskConical className="h-3 w-3 inline mr-1" /> Laboratory</div>
        <div className="p-4">
          <Row label="Lab name" value={p.lab_name || p.display_name} />
          <Row label="Tests offered" value={p.tests_offered ? (Array.isArray(p.tests_offered) ? `${p.tests_offered.length} tests` : listify(p.tests_offered)) : null} />
          <BoolRow label="Home collection" value={p.offers_home_collection} />
          <Row label="Home collection fee" value={p.home_collection_fee ? fmtCurrency(p.home_collection_fee) : null} />
          <BoolRow label="Lab visit" value={p.offers_lab_visit} />
          <Row label="Sample-collection SLA" value={p.sample_collection_timeline ? `${p.sample_collection_timeline} hr` : null} />
          <Row label="Report SLA" value={p.report_generation_timeline ? `${p.report_generation_timeline} hr` : null} />
          <Row label="Service radius" value={p.service_radius_km ? `${p.service_radius_km} km` : null} />
        </div>
      </section>
      <section className={T.card} data-testid="profile-pathology-accreditation">
        <div className={T.sectionHead}><Award className="h-3 w-3 inline mr-1" /> Accreditations & performance</div>
        <div className="p-4">
          <BoolRow label="NABL accredited" value={p.nabl_accredited} />
          <BoolRow label="CAP accredited" value={p.cap_accredited} />
          <BoolRow label="ISO certified" value={p.iso_certified} />
          <Row label="Certifications" value={listify(p.certifications)} />
          <Row label="Total bookings" value={p.total_bookings} />
          <Row label="Completed" value={p.completed_bookings} />
          <Row label="Rating" value={p.average_rating || p.rating ? `${(p.average_rating || p.rating).toFixed(1)} ★${p.total_reviews ? ` · ${p.total_reviews} reviews` : ""}` : null} />
          <Row label="AI recommendation score" value={p.ai_recommendation_score ? p.ai_recommendation_score.toFixed(2) : null} />
          <Row label="Lifetime earnings" value={p.total_earnings ? fmtCurrency(p.total_earnings) : null} />
        </div>
      </section>
    </>
  );
}
