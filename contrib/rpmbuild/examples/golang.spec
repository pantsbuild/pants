# Disable the debug package (and the associated requirements finding) because RPM gets
# confused by prebuilt Go binaries.
%global debug_package %{nil}

Summary: Go language
Name: golang
Version: %{version}
Release: 1%{?dist}
License: GO
Group: Development/Languages
URL: https://golang.org/

BuildRequires: tar

# Disable RPM's standard automatic dependency detection since the Go binaries are static.
AutoReqProv: no

Source: go%{version}.linux-amd64.tar.gz

BuildRoot: %{_tmppath}/%{name}-%{version}-%{release}-root-%(%{__id_u} -n)

%description
Go is an open source programming language that makes it easy to build simple, reliable,
and efficient software.

%prep
# Do not do any standard source unpacking (-T) and make work directory (-c).
%setup -c -T

%build
# No build step since we are just moving files into the RPM_BUILD_ROOT.

%install
rm -rf "%{buildroot}"
mkdir -p "%{buildroot}/usr/local"
tar xzvf "${RPM_SOURCE_DIR}/go%{version}.linux-amd64.tar.gz" -C "%{buildroot}/usr/local"

mkdir -p "%{buildroot}/usr/local/bin"
cd "%{buildroot}/usr/local/bin"
for x in go godoc gofmt ; do
  ln -s "../go/bin/$x" .
done

%files
%defattr(-, root, root, -)
/usr/local/go
/usr/local/bin/go
/usr/local/bin/godoc
/usr/local/bin/gofmt
