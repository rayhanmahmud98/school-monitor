from django.contrib import messages
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render

from accounts.crud import build_crud
from accounts.permissions import ADMIN, TEACHER, role_required
from accounts.scope import scoped_students, teacher_classes
from accounts.utils import paginate

from .forms import ClassForm, StudentDocumentForm, StudentForm, SubjectForm, TransferCertificateForm
from .models import Class, Student, StudentDocument, Subject, TransferCertificate
from .pdf import render_id_cards_pdf


# --- Admin CRUD --------------------------------------------------------------
classes = build_crud(
    ns="students", name="class", slug="classes", model_class=Class, form_cls=ClassForm,
    title="Classes", singular="Class",
    columns=[("Class", "name"), ("Section", "section"), ("Academic year", "academic_year")],
    search_fields=("name", "section", "academic_year"),
)
subjects = build_crud(
    ns="students", name="subject", slug="subjects", model_class=Subject, form_cls=SubjectForm,
    title="Subjects", singular="Subject",
    columns=[("Subject", "name"), ("Code", "code"), ("Class", "class_ref"),
             ("Teacher", "teacher.display_name")],
    search_fields=("name", "code", "teacher__username", "class_ref__name"),
    select_related=("class_ref", "teacher"),
)
students = build_crud(
    ns="students", name="student", slug="records", model_class=Student, form_cls=StudentForm,
    title="Students", singular="Student",
    columns=[("Roll", "roll_no"), ("Name", "full_name"), ("Class", "class_ref"),
             ("Guardian", "guardian_name"), ("Contact", "contact"), ("Active", "is_active")],
    search_fields=("full_name", "guardian_name", "class_ref__name", "contact",
                   "student_id", "email", "phone"),
    select_related=("class_ref",),
)


# --- Teacher (and admin) read-only student list ------------------------------
@role_required(ADMIN, TEACHER)
def my_students(request):
    """Students limited to the teacher's assigned classes (admin sees all).

    Supports filtering by class, a free-text search, and a sort option.
    """
    qs = scoped_students(request.user).select_related("class_ref")
    classes_qs = Class.objects.all() if request.user.role == ADMIN else teacher_classes(request.user)

    class_id = request.GET.get("class", "").strip()
    q = request.GET.get("q", "").strip()
    sort = request.GET.get("sort", "class").strip()

    if class_id.isdigit():
        qs = qs.filter(class_ref_id=class_id)

    if q:
        qs = qs.filter(
            Q(full_name__icontains=q)
            | Q(guardian_name__icontains=q)
            | Q(student_id__icontains=q)
            | Q(roll_no__icontains=q)
        )

    SORTS = {
        # key: (label, order_by tuple)
        "class":        ("Class, then roll no.", ("class_ref__name", "class_ref__section", "roll_no")),
        "class_desc":   ("Class (reverse), then roll no.", ("-class_ref__name", "-class_ref__section", "roll_no")),
        "name":         ("Name (A-Z)", ("full_name",)),
        "name_desc":    ("Name (Z-A)", ("-full_name",)),
        "roll":         ("Roll number", ("roll_no",)),
        "student_id":   ("Student ID", ("student_id",)),
        "newest":       ("Newest admitted first", ("-admission_date", "full_name")),
    }
    if sort not in SORTS:
        sort = "class"
    _, order_by = SORTS[sort]

    page_obj, querystring = paginate(request, qs.order_by(*order_by), 25)

    return render(request, "students/my_students.html", {
        "page_obj": page_obj,
        "qs": querystring,
        "classes": classes_qs,
        "class_id": class_id,
        "q": q,
        "sort": sort,
        "sort_options": [(key, label) for key, (label, _) in SORTS.items()],
    })


# --- Student documents -------------------------------------------------------
@role_required(ADMIN, TEACHER)
def student_documents(request, student_pk):
    """List all documents for a student; admins/teachers can add and delete."""
    student = get_object_or_404(
        scoped_students(request.user).select_related("class_ref"), pk=student_pk
    )
    documents = student.documents.select_related("uploaded_by").all()

    if request.method == "POST":
        form = StudentDocumentForm(request.POST, request.FILES)
        if form.is_valid():
            doc = form.save(commit=False)
            doc.student = student
            doc.uploaded_by = request.user
            doc.save()
            messages.success(request, f"Uploaded: {doc.display_title}")
            return redirect("students:student_documents", student_pk=student.pk)
        messages.error(request, "Please fix the errors below.")
    else:
        form = StudentDocumentForm()

    return render(request, "students/student_documents.html", {
        "student": student,
        "documents": documents,
        "form": form,
    })


@role_required(ADMIN, TEACHER)
def student_document_delete(request, student_pk, pk):
    student = get_object_or_404(scoped_students(request.user), pk=student_pk)
    doc = get_object_or_404(student.documents, pk=pk)

    if request.method == "POST":
        title = doc.display_title
        doc.file.delete(save=False)
        doc.delete()
        messages.success(request, f"Deleted: {title}")
        return redirect("students:student_documents", student_pk=student.pk)

    return render(request, "students/student_document_confirm_delete.html", {
        "student": student, "doc": doc,
    })


@role_required(ADMIN, TEACHER)
def student_document_download(request, student_pk, pk):
    student = get_object_or_404(scoped_students(request.user), pk=student_pk)
    doc = get_object_or_404(student.documents, pk=pk)
    if not doc.file:
        raise Http404("This document has no file attached.")
    filename = f"{student.student_id or student.pk}_{doc.get_kind_display()}_{doc.filename}"
    return FileResponse(doc.file.open("rb"), as_attachment=True, filename=filename)


# --- ID cards ----------------------------------------------------------------
@role_required(ADMIN, TEACHER)
def student_id_card(request, student_pk):
    """Download a single student ID card as a one-card PDF."""
    student = get_object_or_404(
        scoped_students(request.user).select_related("class_ref"), pk=student_pk
    )
    pdf_bytes = render_id_cards_pdf([student])
    filename = f"id_card_{student.student_id or student.pk}.pdf"
    return FileResponse(
        iter([pdf_bytes]), content_type="application/pdf",
        as_attachment=True, filename=filename,
    )


@role_required(ADMIN, TEACHER)
def class_id_cards(request, class_pk):
    """Download a PDF containing ID cards for every active student in a class."""
    cls = get_object_or_404(Class, pk=class_pk)
    student_qs = cls.students.filter(is_active=True).order_by("roll_no")
    if request.user.role == TEACHER:
        allowed = set(scoped_students(request.user).values_list("pk", flat=True))
        student_qs = [s for s in student_qs if s.pk in allowed]
    else:
        student_qs = list(student_qs)

    if not student_qs:
        raise Http404("No active students in this class.")

    pdf_bytes = render_id_cards_pdf(student_qs)
    filename = f"id_cards_class_{cls.pk}.pdf"
    return FileResponse(
        iter([pdf_bytes]), content_type="application/pdf",
        as_attachment=True, filename=filename,
    )


@role_required(ADMIN, TEACHER)
def class_id_cards_page(request):
    """A small form page with a class picker that leads to the class PDF."""
    classes_qs = Class.objects.all().order_by("name", "section")
    if request.user.role == TEACHER:
        classes_qs = teacher_classes(request.user)

    selected = None
    count = 0
    class_id = request.GET.get("class", "").strip()
    if class_id.isdigit():
        selected = classes_qs.filter(pk=class_id).first()
        if selected:
            qs = selected.students.filter(is_active=True)
            if request.user.role == TEACHER:
                allowed = set(scoped_students(request.user).values_list("pk", flat=True))
                count = sum(1 for s in qs if s.pk in allowed)
            else:
                count = qs.count()

    return render(request, "students/class_id_cards.html", {
        "classes": classes_qs,
        "selected": selected,
        "count": count,
    })



# ==============================================================================
# TRANSFER CERTIFICATE
# ==============================================================================
@role_required(ADMIN)
def transfer_certificate_view(request, student_pk):
    """Show, create, or update a student's TC. Issuing a TC marks the student inactive."""
    from .pdf import render_transfer_certificate_pdf
    from academics.audit import log_action  # may not exist - see note below

    student = get_object_or_404(
        Student.objects.select_related("class_ref"), pk=student_pk
    )

    tc = getattr(student, "transfer_certificate", None)

    if request.method == "POST":
        form = TransferCertificateForm(request.POST, instance=tc)
        if form.is_valid():
            new_tc = form.save(commit=False)
            new_tc.student = student
            if not new_tc.pk:
                new_tc.issued_by = request.user
            new_tc.save()

            # Mark the student inactive on first issue.
            if student.is_active:
                student.is_active = False
                student.save(update_fields=["is_active"])

            # Log the action
            try:
                from academics.audit import log_action as academic_log
                academic_log(
                    request,
                    "TC_ISSUED" if not tc else "TC_UPDATED",
                    new_tc,
                    f"TC {new_tc.tc_number} for {student.full_name} ({new_tc.get_reason_display()})",
                )
            except ImportError:
                pass

            messages.success(request, f"Transfer Certificate saved: {new_tc.tc_number}")
            return redirect("students:transfer_certificate", student_pk=student.pk)
        messages.error(request, "Please fix the errors below.")
    else:
        form = TransferCertificateForm(instance=tc)

    return render(request, "students/transfer_certificate.html", {
        "student": student,
        "tc": tc,
        "form": form,
    })


@role_required(ADMIN)
def transfer_certificate_download(request, student_pk):
    """Stream the TC PDF."""
    from .pdf import render_transfer_certificate_pdf

    student = get_object_or_404(Student.objects.select_related("class_ref"), pk=student_pk)
    tc = getattr(student, "transfer_certificate", None)
    if tc is None:
        raise Http404("This student has no transfer certificate yet.")

    pdf_bytes = render_transfer_certificate_pdf(tc, requested_by=request.user)
    filename = f"TC_{tc.tc_number}_{student.full_name.replace(' ', '_')}.pdf"
    return FileResponse(
        iter([pdf_bytes]),
        content_type="application/pdf",
        as_attachment=True,
        filename=filename,
    )


@role_required(ADMIN)
def transfer_certificate_list(request):
    """All issued TCs, newest first, with search."""
    from .models import TransferCertificate

    qs = TransferCertificate.objects.select_related("student", "issued_by").order_by("-issued_at")

    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(
            Q(tc_number__icontains=q)
            | Q(student__full_name__icontains=q)
            | Q(student__student_id__icontains=q)
            | Q(reason_note__icontains=q)
        )

    page_obj, querystring = paginate(request, qs, 25)
    return render(request, "students/transfer_certificate_list.html", {
        "page_obj": page_obj,
        "qs": querystring,
        "q": q,
    })
