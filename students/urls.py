from django.urls import path
from . import views

app_name = "students"

urlpatterns = [
    path("mine/", views.my_students, name="my_students"),
    path("manage/", views.manage_students, name="manage_students"),

    path("transfer-certificates/", views.transfer_certificate_list, name="transfer_certificate_list"),
    path("<int:student_pk>/transfer-certificate/", views.transfer_certificate_view, name="transfer_certificate"),
    path("<int:student_pk>/transfer-certificate.pdf", views.transfer_certificate_download, name="transfer_certificate_download"),

    path("<int:student_pk>/documents/", views.student_documents, name="student_documents"),
    path("<int:student_pk>/documents/<int:pk>/delete/", views.student_document_delete, name="student_document_delete"),
    path("<int:student_pk>/documents/<int:pk>/download/", views.student_document_download, name="student_document_download"),

    # New Profile route
    path("<int:pk>/", views.student_profile, name="student_profile"),
    path("<int:student_pk>/id-card.pdf", views.student_id_card, name="student_id_card"),
    
    path("classes/<int:class_pk>/id-cards.pdf", views.class_id_cards, name="class_id_cards"),
    path("classes/id-cards/", views.class_id_cards_page, name="class_id_cards_page"),

    *views.students.urls,
    *views.classes.urls,
    *views.subjects.urls,
]