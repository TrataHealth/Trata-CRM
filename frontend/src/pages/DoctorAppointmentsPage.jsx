import React from "react";
import { DoctorAppointments } from "../components/doctor/DoctorAppointments";

export default function DoctorAppointmentsPage() {
  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-5" data-testid="doctor-appointments-page">
      <div>
        <div className="overline">My Practice</div>
        <h1 className="font-heading text-2xl sm:text-3xl font-black tracking-tight text-[#091E42] mt-1">Appointments</h1>
        <p className="text-sm text-[#5E6C84] mt-1">Clinic visits, hospital consults and video consults booked with you on the Trata Patient app. Tap one to see the patient and their visits with you.</p>
      </div>
      <DoctorAppointments />
    </div>
  );
}
