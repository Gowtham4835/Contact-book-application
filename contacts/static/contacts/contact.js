$(function () {
    const modalElement = document.getElementById("contact-modal");
    const contactModal = new bootstrap.Modal(modalElement);
 
    const table = $("#contacts-table").DataTable({
        processing: true,
        serverSide: true,
        ajax: {
            url: contactUrls.datatable,
            type: "GET"
        },
        columns: [
            { data: "name" },
            { data: "phone_number" },
            { data: "email" },
            {
                data: "pk",
                orderable: false,
                searchable: false
            }
        ]
    });

 
    function loadForm(url, title) {
        $.get(url, function (html) {
            $("#modal-title").text(title);
            $("#contact-form-container").html(html);
            $("#form-errors").empty();
            contactModal.show();
        });
    }
 
    $("#add-contact").on("click", function () {
        loadForm(contactUrls.create, "Add Contact");
    });
 
    $("#contact-form-container").on(
        "submit",
        "#contact-form",
        function (event) {
            event.preventDefault();
 
            const form = this;
            const formData = new FormData(form);
 
            $.ajax({
                url: $(form).data("url"),
                type: "POST",
                data: formData,
                processData: false,
                contentType: false,
 
                success: function (response) {
                    if (response.success) {
                        contactModal.hide();
                        table.ajax.reload(null, false);
 
                        $("#message").html(
                            '<div class="alert alert-success">' +
                            response.message +
                            "</div>"
                        );
                    }
                },
 
                error: function (xhr) {
                    const response = xhr.responseJSON;
 
                    if (response && response.errors) {
                        const messages = [];
 
                        Object.values(response.errors).forEach(
                            function (errors) {
                                errors.forEach(function (error) {
                                    messages.push(error.message);
                                });
                            }
                        );
 
                        $("#form-errors").text(messages.join(" "));
                    } else {
                        $("#form-errors").text(
                            "Unable to save the contact."
                        );
                    }
                }
            });
        }
    );
 
    $("#contacts-table").on(
        "click",
        ".edit-contact",
        function () {
            loadForm($(this).data("url"), "Edit Contact");
        }
    );
 
    $("#contacts-table").on(
        "click",
        ".delete-contact",
        function () {
            const url = $(this).data("url");
 
            Swal.fire({
                title: "Delete contact?",
                text: "This action cannot be undone.",
                icon: "warning",
                showCancelButton: true,
                confirmButtonText: "Yes, delete it"
            }).then(function (result) {
                if (!result.isConfirmed) {
                    return;
                }
 
                $.ajax({
                    url: url,
                    type: "POST",
                    headers: {
                        "X-CSRFToken": $(
                            "#contact-form [name=csrfmiddlewaretoken]"
                        ).val() || getCookie("csrftoken")
                    },
 
                    success: function (response) {
                        if (response.success) {
                            table.ajax.reload(null, false);
 
                            Swal.fire(
                                "Deleted!",
                                response.message,
                                "success"
                            );
                        }
                    },
 
                    error: function () {
                        Swal.fire(
                            "Error",
                            "Unable to delete the contact.",
                            "error"
                        );
                    }
                });
            });
        }
    );
 
    function getCookie(name) {
        const cookies = document.cookie.split(";");
 
        for (const cookie of cookies) {
            const item = cookie.trim();
 
            if (item.startsWith(name + "=")) {
                return decodeURIComponent(
                    item.substring(name.length + 1)
                );
            }
        }
 
        return "";
    }
});