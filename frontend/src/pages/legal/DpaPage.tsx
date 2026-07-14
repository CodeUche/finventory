import LegalShell from './LegalShell'

export default function DpaPage() {
  return (
    <LegalShell title="Data Processing Agreement">
      <h2>1. Introduction and Scope</h2>
      <p>This Data Processing Agreement (“DPA”) forms part of, and is subject to, the Terms and Conditions of Use (the “Agreement”) between <strong>Audity Technologies Limited</strong> (RC 9395403, 14 First Unity Estate, Ajah, Lagos, Nigeria — “Audity”, “Processor”) and the customer that has agreed to the Agreement (“Customer”, “Controller”, “you”). It governs Audity’s processing of Personal Data on the Customer’s behalf in connection with the Services.</p>
      <p>This DPA applies where and to the extent Audity processes, as a processor, Personal Data contained in the Content that the Customer or its Authorised Users upload to or generate through the Services. It reflects the parties’ agreement on data protection in accordance with the Nigeria Data Protection Act 2023 (the “NDPA”) and, where applicable, the EU GDPR. Where there is a conflict between this DPA and the rest of the Agreement on data protection, this DPA prevails.</p>

      <h2>2. Definitions</h2>
      <p><strong>“Personal Data”</strong> means any information relating to an identified or identifiable natural person contained in the Content and processed by Audity on the Customer’s behalf. <strong>“Data Subject”</strong> is the person to whom Personal Data relates. <strong>“Processing”</strong> means any operation performed on Personal Data. <strong>“Sub-processor”</strong> means any third party engaged by Audity to process Personal Data on the Customer’s behalf. <strong>“Personal Data Breach”</strong> means a breach of security leading to the accidental or unlawful destruction, loss, alteration, unauthorised disclosure of, or access to, Personal Data.</p>

      <h2>3. Roles of the Parties</h2>
      <p>The Customer is the Controller and Audity is the Processor in respect of the Personal Data processed under this DPA. Where the Customer is itself a processor acting on behalf of a third-party controller (for example, where the Customer is a Partner processing a client’s data), Audity acts as a sub-processor, and the Customer warrants that it has the authority of the relevant controller to appoint Audity on these terms. Each party is responsible for complying with its own obligations under applicable data protection law.</p>

      <h2>4. Customer Obligations</h2>
      <p>The Customer: shall maintain throughout the term a lawful basis under the NDPA for the processing of the Personal Data it uploads; shall provide all privacy notices and obtain all consents and authorisations required for Audity to process the Personal Data as contemplated; warrants that its processing instructions are lawful and that the Personal Data has been collected and may lawfully be processed; and is solely responsible for the accuracy, quality, and legality of the Personal Data and the means by which it acquired it.</p>

      <h2>5. Audity Obligations as Processor</h2>
      <p><strong>Process on instructions.</strong> Process the Personal Data only on the Customer’s documented instructions, including the Agreement, this DPA, and the Customer’s configuration of the Services, unless required to process otherwise by law (in which case Audity will, where legally permitted, inform the Customer first).</p>
      <p><strong>Confidentiality.</strong> Ensure that persons authorised to process the Personal Data are bound by appropriate confidentiality obligations.</p>
      <p><strong>Security.</strong> Implement and maintain the technical and organisational security measures described in Annex B, appropriate to the risk.</p>
      <p><strong>Sub-processing.</strong> Engage Sub-processors only in accordance with Section 6.</p>
      <p><strong>Assistance with Data Subject rights.</strong> Taking into account the nature of the processing, provide reasonable assistance, including through the self-service export and deletion features of the Services, to enable the Customer to respond to Data Subject requests under the NDPA.</p>
      <p><strong>Assistance with compliance.</strong> Provide reasonable assistance with the Customer’s obligations regarding security, Personal Data Breach notification, data protection impact assessments, and prior consultation with the NDPC, taking into account the information available to Audity.</p>
      <p><strong>Breach notification.</strong> Notify the Customer without undue delay after becoming aware of a Personal Data Breach affecting the Customer’s Personal Data, and provide information reasonably available to assist the Customer in meeting its own notification obligations.</p>
      <p><strong>Deletion or return.</strong> On termination or expiry, and subject to the retention window in the Agreement, delete or return the Personal Data at the Customer’s choice, save to the extent Audity is required by law to retain it or it remains in routine backups pending overwriting.</p>
      <p><strong>Records and audits.</strong> Make available information reasonably necessary to demonstrate compliance and allow for and contribute to audits by the Customer or its mandated auditor, on reasonable prior notice, no more than once per year (unless required by a regulator or following a Personal Data Breach), subject to confidentiality and to not compromising the security or data of other customers.</p>

      <h2>6. Sub-processors</h2>
      <p>The Customer provides a general authorisation for Audity to engage Sub-processors in connection with the Services. Audity’s current key Sub-processors, by category, are set out in Annex C. Audity shall impose on each Sub-processor data-protection obligations no less protective than those in this DPA and remains responsible to the Customer for their performance. Where Audity intends to add or replace a Sub-processor, it will update Annex C and, where reasonably practicable, give the Customer prior notice and an opportunity to object on reasonable data-protection grounds.</p>

      <h2>7. International Transfers</h2>
      <p>Where Audity or its Sub-processors process Personal Data outside Nigeria, Audity shall ensure that such transfers are carried out in accordance with the NDPA, including by transferring only to jurisdictions recognised as providing an adequate level of protection or by putting in place appropriate safeguards such as contractual data-protection clauses.</p>

      <h2>8. Liability</h2>
      <p>Each party’s liability arising out of or related to this DPA is subject to the limitations and exclusions of liability set out in the Agreement, and any reference to a party’s liability means the aggregate liability of that party under the Agreement and this DPA taken together. Nothing in this DPA limits any liability that cannot be limited under applicable law.</p>

      <h2>9. Term, Termination, and Governing Law</h2>
      <p>This DPA takes effect when the Customer accepts the Agreement and continues until the Agreement terminates or expires and Audity has ceased processing the Personal Data. This DPA is governed by the laws of the Federal Republic of Nigeria, and any dispute is subject to the dispute-resolution and governing-law provisions of the Agreement.</p>

      <h2>Annex A — Details of Processing</h2>
      <table>
        <tbody>
          <tr><th>Subject matter</th><td>Provision of the Audity accounting, payroll, inventory, invoicing, tax, and business-management Services.</td></tr>
          <tr><th>Duration</th><td>For the term of the Agreement and any applicable retention window thereafter.</td></tr>
          <tr><th>Nature and purpose</th><td>Hosting, storage, processing, and transmission of Personal Data to operate, maintain, secure, and provide the Services and their features.</td></tr>
          <tr><th>Categories of Data Subjects</th><td>The Customer’s employees, contractors, customers, suppliers, and other individuals whose data the Customer includes in the Content.</td></tr>
          <tr><th>Types of Personal Data</th><td>Identity and contact details; role and employment details; payroll, salary, pension, and tax data; bank account and payment references; transaction and invoice records; and any other Personal Data the Customer chooses to input.</td></tr>
          <tr><th>Special-category data</th><td>The Services are not designed for special-category data; the Customer should not upload such data except as strictly necessary and lawful.</td></tr>
        </tbody>
      </table>

      <h2>Annex B — Technical and Organisational Security Measures</h2>
      <p>Audity maintains security measures including, as appropriate to the risk:</p>
      <ul>
        <li>encryption of Personal Data in transit;</li>
        <li>logical tenant isolation, so that each Organisation’s data is segregated and access is scoped to that Organisation;</li>
        <li>role-based access controls and granular, module-level permissions;</li>
        <li>authentication controls, including hashed password storage and token-based session management;</li>
        <li>logging, monitoring, and audit trails of key actions within the Services;</li>
        <li>access controls and confidentiality obligations for Audity personnel, on a least-privilege basis;</li>
        <li>regular backups and measures designed to support availability and recovery; and</li>
        <li>periodic review of security practices and dependencies.</li>
      </ul>

      <h2>Annex C — Sub-processors (by category)</h2>
      <p>Audity engages Sub-processors in the following categories to support the Services. A current, specific list is available to the Customer on request.</p>
      <table>
        <thead><tr><th>Category</th><th>Purpose</th></tr></thead>
        <tbody>
          <tr><td>Cloud hosting and storage</td><td>Hosting of the application, database, and file/media storage.</td></tr>
          <tr><td>Payment processing</td><td>Collection of Subscription fees and, where used, payment features and bank-account resolution.</td></tr>
          <tr><td>Product analytics</td><td>Understanding feature usage and improving the Services.</td></tr>
          <tr><td>Email delivery</td><td>Sending transactional and, where opted in, product communications.</td></tr>
          <tr><td>E-invoicing System Integrator</td><td>Transmission of invoices to the FIRS e-invoicing framework, where enabled.</td></tr>
          <tr><td>Open banking provider</td><td>Bank-account linking and retrieval of bank data, where enabled by the Customer.</td></tr>
        </tbody>
      </table>
    </LegalShell>
  )
}
