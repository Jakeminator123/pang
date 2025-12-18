"use client";

import { useEffect, useState, useMemo } from "react";
import { useParams } from "next/navigation";
import DashboardPageLayout from "@/components/dashboard/layout";
import { Building2, Users, ArrowLeft, Search, MapPin, Briefcase, User, Download } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { format } from "date-fns";
import Link from "next/link";

interface CompanyData {
  [key: string]: any;
}

interface PersonData {
  [key: string]: any;
}

export default function DateDetailPage() {
  const params = useParams();
  const date = params.date as string;
  const [data, setData] = useState<{
    companies: CompanyData[];
    people: PersonData[];
    companyDetails?: CompanyData[];
    stats: any;
    source?: string;
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<"companies" | "people">("companies");
  const [searchQuery, setSearchQuery] = useState("");

  useEffect(() => {
    if (date) {
      fetchData();
    }
  }, [date]);

  const fetchData = async () => {
    try {
      const response = await fetch(`/api/data/${date}`);
      if (response.ok) {
        const result = await response.json();
        const companies = result.sheets[result.sheetNames[0]] || [];
        const people = result.sheets["Personer"] || [];
        const companyDetails = result.sheets["CompanyDetails"] || [];
        setData({
          companies,
          people,
          companyDetails: companyDetails.length > 0 ? companyDetails : undefined,
          stats: result.stats,
          source: result.source || "excel",
        });
      }
    } catch (error) {
      console.error("Error fetching data:", error);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <DashboardPageLayout
        header={{
          title: "Loading...",
          description: "Fetching data",
        }}
      >
        <div className="flex items-center justify-center h-64">
          <div className="text-muted-foreground">Loading...</div>
        </div>
      </DashboardPageLayout>
    );
  }

  if (!data) {
    return (
      <DashboardPageLayout
        header={{
          title: "Error",
          description: "Could not load data",
        }}
      >
        <Card>
          <CardContent className="pt-6">
            <div className="text-center text-muted-foreground">
              No data found for this date.
            </div>
          </CardContent>
        </Card>
      </DashboardPageLayout>
    );
  }

  const dateObj = new Date(
    parseInt(date.slice(0, 4)),
    parseInt(date.slice(4, 6)) - 1,
    parseInt(date.slice(6, 8))
  );

  return (
    <DashboardPageLayout
      header={{
        title: format(dateObj, "PPP"),
        description: `Data for ${date}`,
      }}
    >
      <div className="mb-6 flex items-center justify-between">
        <Link href="/">
          <Button variant="outline" size="sm">
            <ArrowLeft className="mr-2 h-4 w-4" />
            Back to Overview
          </Button>
        </Link>
        <Button
          variant="destructive"
          size="sm"
          onClick={() => {
            window.location.href = `/api/download/${date}`;
          }}
        >
          <Download className="mr-2 h-4 w-4" />
          Download ZIP
        </Button>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-medium">Companies</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{data.stats.totalCompanies}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-medium">People</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{data.stats.totalPeople}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-medium">Data Source</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {data.source === "sqlite" ? "SQLite" : "Excel"}
            </div>
            <div className="text-xs text-muted-foreground mt-1">
              {data.stats.hasPeopleData ? "Complete" : "Basic"} data
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Tabs */}
      <div className="mb-4 flex gap-2 border-b">
        <Button
          variant={activeTab === "companies" ? "default" : "ghost"}
          onClick={() => setActiveTab("companies")}
          className="rounded-none border-b-2 border-transparent data-[state=active]:border-primary"
        >
          <Building2 className="mr-2 h-4 w-4" />
          Companies ({data.companies.length})
        </Button>
        {data.people.length > 0 && (
          <Button
            variant={activeTab === "people" ? "default" : "ghost"}
            onClick={() => setActiveTab("people")}
            className="rounded-none border-b-2 border-transparent data-[state=active]:border-primary"
          >
            <Users className="mr-2 h-4 w-4" />
            People ({data.people.length})
          </Button>
        )}
      </div>

      {/* Data Tables */}
      {activeTab === "companies" && (
        <Card>
          <CardHeader>
            <CardTitle>Companies</CardTitle>
            <CardDescription>All companies in this dataset</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    {data.companies.length > 0 &&
                      Object.keys(data.companies[0]).slice(0, 10).map((key) => (
                        <TableHead key={key} className="capitalize">
                          {key.replace(/_/g, " ")}
                        </TableHead>
                      ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.companies.slice(0, 50).map((company, idx) => (
                    <TableRow key={idx}>
                      {Object.keys(company).slice(0, 10).map((key) => (
                        <TableCell key={key} className="max-w-xs truncate">
                          {String(company[key] || "")}
                        </TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              {data.companies.length > 50 && (
                <div className="text-sm text-muted-foreground mt-4 text-center">
                  Showing first 50 of {data.companies.length} companies
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {activeTab === "people" && data.people.length > 0 && (
        <PeopleTable 
          people={data.people} 
          searchQuery={searchQuery}
          setSearchQuery={setSearchQuery}
        />
      )}
    </DashboardPageLayout>
  );
}

function PeopleTable({ 
  people, 
  searchQuery, 
  setSearchQuery 
}: { 
  people: PersonData[]; 
  searchQuery: string;
  setSearchQuery: (query: string) => void;
}) {
  // Define important columns to show first
  const importantColumns = [
    'fornamn', 'efternamn', 'mellannamn', 
    'roll', 'titel', 
    'företagsnamn', 'org_nr',
    'ort', 'postnummer', 'adress',
    'personnummer'
  ];

  // Filter and sort people
  const filteredPeople = useMemo(() => {
    let filtered = [...people];
    
    // Apply search filter
    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase();
      filtered = filtered.filter((person) => {
        const searchableText = Object.values(person)
          .map(v => String(v || '').toLowerCase())
          .join(' ');
        return searchableText.includes(query);
      });
    }
    
    return filtered;
  }, [people, searchQuery]);

  // Get all columns, prioritizing important ones
  const allColumns = useMemo(() => {
    if (people.length === 0) return [];
    
    const allKeys = new Set<string>();
    people.forEach(p => Object.keys(p).forEach(k => allKeys.add(k)));
    
    const important = importantColumns.filter(k => allKeys.has(k));
    const others = Array.from(allKeys).filter(k => !importantColumns.includes(k));
    
    return [...important, ...others];
  }, [people]);

  // Get display name for column
  const getColumnDisplayName = (key: string) => {
    const names: Record<string, string> = {
      'fornamn': 'Förnamn',
      'efternamn': 'Efternamn',
      'mellannamn': 'Mellannamn',
      'roll': 'Roll',
      'titel': 'Titel',
      'företagsnamn': 'Företag',
      'org_nr': 'Org.nr',
      'ort': 'Ort',
      'postnummer': 'Postnummer',
      'adress': 'Adress',
      'personnummer': 'Personnummer',
      'kungörelse_id': 'Kungörelse ID'
    };
    return names[key] || key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
  };

  // Format person name
  const formatPersonName = (person: PersonData) => {
    const parts = [];
    if (person.fornamn) parts.push(person.fornamn);
    if (person.mellannamn) parts.push(person.mellannamn);
    if (person.efternamn) parts.push(person.efternamn);
    return parts.length > 0 ? parts.join(' ') : '—';
  };

  // Get role badge variant
  const getRoleBadgeVariant = (role: string) => {
    if (role?.includes('Styrelseledamot')) return 'default';
    if (role?.includes('Styrelsesuppleant')) return 'secondary';
    return 'outline';
  };

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle>Board Members & People</CardTitle>
            <CardDescription>
              {filteredPeople.length === people.length 
                ? `All ${people.length} people extracted from board data`
                : `Showing ${filteredPeople.length} of ${people.length} people`
              }
            </CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <div className="mb-4">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Search by name, company, role, city..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-10"
            />
          </div>
        </div>
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="min-w-[200px]">Name</TableHead>
                <TableHead className="min-w-[150px]">Role</TableHead>
                <TableHead className="min-w-[200px]">Company</TableHead>
                <TableHead className="min-w-[120px]">Location</TableHead>
                {allColumns.filter(c => 
                  !['fornamn', 'efternamn', 'mellannamn', 'roll', 'titel', 'företagsnamn', 'org_nr', 'ort', 'postnummer', 'adress'].includes(c)
                ).map((key) => (
                  <TableHead key={key} className="min-w-[100px]">
                    {getColumnDisplayName(key)}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredPeople.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={allColumns.length + 4} className="text-center py-8 text-muted-foreground">
                    No people found matching your search
                  </TableCell>
                </TableRow>
              ) : (
                filteredPeople.slice(0, 200).map((person, idx) => (
                  <TableRow key={idx} className="hover:bg-muted/50">
                    <TableCell className="font-medium">
                      <div className="flex items-center gap-2">
                        <User className="h-4 w-4 text-muted-foreground" />
                        <div>
                          <div className="font-semibold">{formatPersonName(person)}</div>
                          {person.personnummer && (
                            <div className="text-xs text-muted-foreground font-mono">
                              {person.personnummer}
                            </div>
                          )}
                        </div>
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-col gap-1">
                        {person.roll && (
                          <Badge variant={getRoleBadgeVariant(person.roll)} className="w-fit">
                            {person.roll}
                          </Badge>
                        )}
                        {person.titel && person.titel !== person.roll && (
                          <span className="text-xs text-muted-foreground">{person.titel}</span>
                        )}
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <Briefcase className="h-3 w-3 text-muted-foreground" />
                        <div>
                          <div className="font-medium">{person.företagsnamn || '—'}</div>
                          {person.org_nr && (
                            <div className="text-xs text-muted-foreground font-mono">
                              {person.org_nr}
                            </div>
                          )}
                        </div>
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <MapPin className="h-3 w-3 text-muted-foreground" />
                        <div>
                          {person.ort && (
                            <div className="font-medium">{person.ort}</div>
                          )}
                          {person.postnummer && (
                            <div className="text-xs text-muted-foreground">
                              {person.postnummer}
                            </div>
                          )}
                          {person.adress && !person.ort && (
                            <div className="text-xs text-muted-foreground truncate max-w-[150px]">
                              {person.adress}
                            </div>
                          )}
                        </div>
                      </div>
                    </TableCell>
                    {allColumns.filter(c => 
                      !['fornamn', 'efternamn', 'mellannamn', 'roll', 'titel', 'företagsnamn', 'org_nr', 'ort', 'postnummer', 'adress', 'personnummer'].includes(c)
                    ).map((key) => (
                      <TableCell key={key} className="max-w-xs truncate text-sm">
                        {String(person[key] || '—')}
                      </TableCell>
                    ))}
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
          {filteredPeople.length > 200 && (
            <div className="text-sm text-muted-foreground mt-4 text-center">
              Showing first 200 of {filteredPeople.length} people
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

